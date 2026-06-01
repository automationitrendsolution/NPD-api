"""
Brand Analytics ingestion pipeline orchestrator.

This module ties spapi_client.py and db.py together into one callable function.
It implements the exact flow described in the technical overview:

    SP-API Reports request
      ↓
    Create Brand Analytics Search Terms report
      ↓
    Poll report status until complete
      ↓
    Download report document
      ↓
    Decompress if required
      ↓
    Parse search-term rows
      ↓
    Write rows into local SQLite database
      ↓
    Index search_term, frequency_rank, clicked_product
      ↓
    Use local lookup during Tier 1 scoring

The main entry point is run_ingestion(). It returns a result dict that
is also passed back through the management command and the API endpoint.
"""

import time
from datetime import datetime, timezone

from . import db as ba_db
from . import spapi_client as spapi


# ── Polling config ────────────────────────────────────────────────────────────
# SP-API builds reports asynchronously. Large BA reports can take 5–30 minutes.
# We poll every POLL_INTERVAL_SECONDS until done or until MAX_POLL_ATTEMPTS.

POLL_INTERVAL_SECONDS = 30   # How many seconds to wait between status checks
MAX_POLL_ATTEMPTS = 60       # 60 × 30s = 30 minutes maximum wait


def run_ingestion(
    db_path: str,
    data_start_date: str,
    data_end_date: str,
    report_period: str = "MONTH",
    report_date_label: str = None,
) -> dict:
    """
    Runs the full Brand Analytics search-term ingestion pipeline end-to-end.

    Call this from the management command or from a scheduled job.

    Parameters
    ----------
    db_path : str
        Absolute path to the SQLite file. init_db() is called automatically
        so the file and schema are created if they don't exist yet.

    data_start_date : str
        Start of the reporting window, ISO 8601.
        Example: "2026-05-01T00:00:00Z"

    data_end_date : str
        End of the reporting window, ISO 8601.
        Example: "2026-05-31T23:59:59Z"

    report_period : str
        "MONTH", "WEEK", or "DAY" — how Amazon aggregates the data.
        Use MONTH for weekly ingestion (it gives the fullest picture).

    report_date_label : str, optional
        A human-readable label stored alongside each row, e.g. "2026-05".
        Defaults to the year-month of data_start_date.

    Returns
    -------
    dict with keys:
        status          : "success" or "error"
        report_id       : str — the SP-API report ID
        report_date     : str — the label stored in the database
        rows_inserted   : int
        duration_seconds: float
        error           : str — present only when status == "error"
    """
    started_at = time.monotonic()

    # Derive a period label from the start date if none was supplied
    if not report_date_label:
        try:
            dt = datetime.fromisoformat(data_start_date.replace("Z", "+00:00"))
            report_date_label = dt.strftime("%Y-%m")
        except Exception:
            report_date_label = data_start_date[:7]  # fallback: first 7 chars

    # Ensure the database and schema exist before we start
    ba_db.init_db(db_path)

    report_id = None
    rows_inserted = 0

    try:
        # ── Step 1: Request the report ─────────────────────────────────────────
        print(f"[BA ingestion] Requesting report for {data_start_date} → {data_end_date}")
        report_id = spapi.create_search_terms_report(
            data_start_date=data_start_date,
            data_end_date=data_end_date,
            report_period=report_period,
        )
        print(f"[BA ingestion] Report requested. reportId={report_id}")

        # ── Step 2: Poll until the report is ready ─────────────────────────────
        # Amazon builds reports asynchronously. We wait in a loop.
        report_document_id = _poll_until_done(report_id)

        # ── Step 3: Get the download URL ───────────────────────────────────────
        print(f"[BA ingestion] Fetching download URL for document {report_document_id}")
        download_url, is_gzip = spapi.get_report_document_url(report_document_id)

        # ── Step 4: Download and decompress ───────────────────────────────────
        print(f"[BA ingestion] Downloading report (gzip={is_gzip})")
        tsv_text = spapi.download_and_decompress(download_url, is_gzip)
        print(f"[BA ingestion] Downloaded {len(tsv_text):,} characters")

        # ── Step 5: Parse TSV rows ─────────────────────────────────────────────
        rows = ba_db.parse_report_tsv(tsv_text, report_date=report_date_label)
        print(f"[BA ingestion] Parsed {len(rows):,} rows")

        if not rows:
            raise ValueError("Report downloaded but contained no data rows after parsing")

        # ── Step 6: Write to SQLite ────────────────────────────────────────────
        print(f"[BA ingestion] Writing to SQLite at {db_path}")
        rows_inserted = ba_db.insert_rows(db_path, rows)
        print(f"[BA ingestion] Inserted {rows_inserted:,} rows")

        # ── Log the success ────────────────────────────────────────────────────
        ba_db.log_ingestion(
            db_path=db_path,
            report_date=report_date_label,
            report_period=report_period,
            status="success",
            rows_inserted=rows_inserted,
        )

        duration = round(time.monotonic() - started_at, 1)
        print(f"[BA ingestion] Done in {duration}s. {rows_inserted:,} rows indexed.")

        return {
            "status": "success",
            "report_id": report_id,
            "report_date": report_date_label,
            "rows_inserted": rows_inserted,
            "duration_seconds": duration,
        }

    except Exception as exc:
        error_msg = str(exc)
        duration = round(time.monotonic() - started_at, 1)
        print(f"[BA ingestion] FAILED after {duration}s: {error_msg}")

        ba_db.log_ingestion(
            db_path=db_path,
            report_date=report_date_label,
            report_period=report_period,
            status="error",
            rows_inserted=rows_inserted,
            error_message=error_msg,
        )

        return {
            "status": "error",
            "report_id": report_id,
            "report_date": report_date_label,
            "rows_inserted": rows_inserted,
            "duration_seconds": duration,
            "error": error_msg,
        }


def _poll_until_done(report_id: str) -> str:
    """
    Polls get_report_status() until the report is DONE, then returns
    the reportDocumentId needed to download the file.

    Raises RuntimeError if the report is cancelled, fatal, or times out.

    Parameters
    ----------
    report_id : str
        The reportId returned by create_search_terms_report().

    Returns
    -------
    str
        The reportDocumentId to pass to get_report_document_url().
    """
    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        status_data = spapi.get_report_status(report_id)
        processing_status = status_data.get("processingStatus", "UNKNOWN")

        print(
            f"[BA ingestion] Poll {attempt}/{MAX_POLL_ATTEMPTS}: "
            f"status={processing_status}"
        )

        if processing_status == "DONE":
            document_id = status_data.get("reportDocumentId")
            if not document_id:
                raise RuntimeError(
                    f"Report {report_id} is DONE but has no reportDocumentId. "
                    f"Full response: {status_data}"
                )
            return document_id

        if processing_status in ("CANCELLED", "FATAL"):
            raise RuntimeError(
                f"Report {report_id} ended with status={processing_status}. "
                f"Check Seller Central for details."
            )

        # IN_QUEUE or IN_PROGRESS — wait and try again
        if attempt < MAX_POLL_ATTEMPTS:
            time.sleep(POLL_INTERVAL_SECONDS)

    raise RuntimeError(
        f"Report {report_id} did not complete after "
        f"{MAX_POLL_ATTEMPTS * POLL_INTERVAL_SECONDS // 60} minutes. "
        f"Last status: {processing_status}"
    )
