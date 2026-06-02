"""
MongoDB database layer for the Brand Analytics search-term index.

Replaces the SQLite implementation. Data is stored in two MongoDB collections:
  - ba_search_terms   — keyword rows from Amazon Brand Analytics reports
  - ba_ingestion_log  — audit trail of ingestion runs

All function signatures keep the db_path parameter for backward compatibility
with existing callers (settings.BA_DB_PATH), but the parameter is ignored.
The MongoDB connection is always established via the MONGO_URI env variable.

Schema (ba_search_terms collection)
------------------------------------
{
    report_date:          "2026-05",       # YYYY-MM
    search_term:          "bamboo mug",    # normalised to lowercase
    search_frequency_rank: 12345,
    clicked_asin_1:       "B0...",
    clicked_title_1:      "...",
    click_share_1:        0.35,
    conversion_share_1:   0.22,
    clicked_asin_2:       "B0...",
    clicked_title_2:      "...",
    click_share_2:        0.18,
    conversion_share_2:   0.12,
    clicked_asin_3:       "B0...",
    clicked_title_3:      "...",
    click_share_3:        0.10,
    conversion_share_3:   0.08,
    ingested_at:          "2026-06-01T10:00:00+00:00"
}
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pymongo import MongoClient, ASCENDING, DESCENDING


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_dotenv():
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split("#")[0] if '"' not in value and "'" not in value else value
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

_mongo_client: Optional[MongoClient] = None


def _get_client() -> MongoClient:
    global _mongo_client
    if _mongo_client is None:
        uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/npd_db")
        _mongo_client = MongoClient(uri)
    return _mongo_client


def _get_db():
    db_name = os.getenv("MONGO_DB", "npd_db")
    return _get_client()[db_name]


# ── Schema initialisation ─────────────────────────────────────────────────────

def init_db(db_path: str = None) -> None:
    """
    Creates MongoDB indexes for fast keyword lookups.
    Safe to call on every startup — create_index is idempotent.
    """
    db = _get_db()
    db["ba_search_terms"].create_index(
        [("search_term", ASCENDING)], name="idx_search_term"
    )
    db["ba_search_terms"].create_index(
        [("report_date", DESCENDING), ("search_term", ASCENDING)],
        name="idx_date_term",
    )
    db["ba_ingestion_log"].create_index(
        [("completed_at", DESCENDING)], name="idx_log_completed"
    )


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_share(value: str) -> Optional[float]:
    """
    Converts a share string like "12.5%" or "0.125" to a float (0.0–1.0).
    Returns None if the value is empty or unparseable.
    """
    if not value or not value.strip():
        return None
    v = value.strip().rstrip("%")
    try:
        f = float(v)
        return f / 100.0 if f > 1.0 else f
    except ValueError:
        return None


def _parse_rank(value: str) -> Optional[int]:
    """Converts a rank string to int, returns None on failure."""
    if not value or not value.strip():
        return None
    try:
        return int(value.strip().replace(",", ""))
    except ValueError:
        return None


def parse_report_tsv(tsv_text: str, report_date: str) -> list:
    """
    Parses the Brand Analytics Search Terms TSV report into a list of dicts
    ready to be inserted by insert_rows().

    Expected TSV columns (Amazon's standard format):
        Department Name | Search Term | Search Frequency Rank |
        #1 Clicked ASIN | #1 Product Title | #1 Click Share | #1 Conversion Share |
        #2 Clicked ASIN | #2 Product Title | #2 Click Share | #2 Conversion Share |
        #3 Clicked ASIN | #3 Product Title | #3 Click Share | #3 Conversion Share
    """
    lines = tsv_text.strip().splitlines()
    if not lines:
        return []

    rows = []
    now = _now_iso()

    for line in lines[1:]:
        if not line.strip():
            continue
        cols = line.split("\t")
        while len(cols) < 15:
            cols.append("")

        rows.append({
            "report_date":           report_date,
            "search_term":           cols[1].strip().lower(),
            "search_frequency_rank": _parse_rank(cols[2]),
            "clicked_asin_1":        cols[3].strip() or None,
            "clicked_title_1":       cols[4].strip() or None,
            "click_share_1":         _parse_share(cols[5]),
            "conversion_share_1":    _parse_share(cols[6]),
            "clicked_asin_2":        cols[7].strip() or None,
            "clicked_title_2":       cols[8].strip() or None,
            "click_share_2":         _parse_share(cols[9]),
            "conversion_share_2":    _parse_share(cols[10]),
            "clicked_asin_3":        cols[11].strip() or None,
            "clicked_title_3":       cols[12].strip() or None,
            "click_share_3":         _parse_share(cols[13]),
            "conversion_share_3":    _parse_share(cols[14]),
            "ingested_at":           now,
        })

    return rows


# ── Insert ────────────────────────────────────────────────────────────────────

def insert_rows(db_path: str, rows: list) -> int:
    """
    Bulk-inserts parsed report rows into ba_search_terms.

    Before inserting, deletes any existing rows with the same report_date
    so re-running the ingestion for the same period is idempotent.

    Returns number of rows inserted.
    """
    if not rows:
        return 0

    report_date = rows[0]["report_date"]
    col = _get_db()["ba_search_terms"]

    col.delete_many({"report_date": report_date})
    col.insert_many(rows, ordered=False)
    return len(rows)


# ── Lookup ────────────────────────────────────────────────────────────────────

def lookup(db_path: str, search_term: str, report_date: str = None) -> Optional[dict]:
    """
    Looks up a single keyword in the BA index.

    Returns the most recent matching document, or None if not found.

    Parameters
    ----------
    db_path : str
        Ignored — kept for backward compatibility.
    search_term : str
        Keyword to search for (case-insensitive).
    report_date : str, optional
        If supplied, restricts the lookup to that reporting period.
    """
    term = search_term.strip().lower()
    col = _get_db()["ba_search_terms"]

    query = {"search_term": term}
    if report_date:
        query["report_date"] = report_date

    doc = col.find_one(
        query,
        {"_id": 0},
        sort=[("report_date", DESCENDING), ("search_frequency_rank", ASCENDING)],
    )
    return doc


def lookup_batch(db_path: str, keywords: list, report_date: str = None) -> dict:
    """
    Looks up multiple keywords in a single MongoDB query.

    Returns
    -------
    dict
        { keyword: row_dict_or_None, ... }
        Every input keyword is present as a key.
    """
    if not keywords:
        return {}

    normalised = [k.strip().lower() for k in keywords]
    col = _get_db()["ba_search_terms"]

    query = {"search_term": {"$in": normalised}}
    if report_date:
        query["report_date"] = report_date

    docs = list(col.find(
        query,
        {"_id": 0},
        sort=[("report_date", DESCENDING), ("search_frequency_rank", ASCENDING)],
    ))

    result = {k: None for k in normalised}
    for doc in docs:
        term = doc["search_term"]
        if result[term] is None:
            result[term] = doc

    return result


def get_top_clicked_asins(db_path: str, search_term: str) -> list:
    """
    Returns the list of top-clicked ASINs for a keyword (up to 3).

    The Tier 1 scorer uses this to know which products to pull
    product detail pages for.
    """
    row = lookup(db_path, search_term)
    if not row:
        return []

    asins = []
    for i in (1, 2, 3):
        asin = row.get(f"clicked_asin_{i}")
        if asin:
            asins.append(asin)
    return asins


# ── Ingestion log ─────────────────────────────────────────────────────────────

def log_ingestion(
    db_path: str,
    report_date: str,
    report_period: str,
    status: str,
    rows_inserted: int = 0,
    error_message: str = "",
) -> None:
    """
    Records the outcome of one ingestion run in ba_ingestion_log.
    """
    _get_db()["ba_ingestion_log"].insert_one({
        "report_date":   report_date,
        "report_period": report_period,
        "status":        status,
        "rows_inserted": rows_inserted,
        "error_message": error_message,
        "completed_at":  _now_iso(),
    })


def get_latest_ingestion(db_path: str) -> Optional[dict]:
    """Returns the most recent successful ingestion log entry."""
    doc = _get_db()["ba_ingestion_log"].find_one(
        {"status": "success"},
        {"_id": 0},
        sort=[("completed_at", DESCENDING)],
    )
    return doc


def get_db_stats(db_path: str) -> dict:
    """Returns a summary of what is currently in the database."""
    try:
        col = _get_db()["ba_search_terms"]
        total = col.count_documents({})
        dates = col.distinct("report_date")
        dates.sort(reverse=True)
        return {
            "total_terms": total,
            "report_dates": dates,
        }
    except Exception:
        return {"total_terms": 0, "report_dates": []}
