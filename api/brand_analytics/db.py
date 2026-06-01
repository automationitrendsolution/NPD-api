"""
SQLite database layer for the Brand Analytics search-term index.

Why SQLite instead of the Django ORM?
--------------------------------------
Brand Analytics reports can contain hundreds of thousands of rows.
The ingestion job needs to bulk-insert them as fast as possible and then
do millisecond keyword lookups during Tier 1 scoring.

Using SQLite directly (via Python's sqlite3 stdlib module) gives us:
- executemany() for fast bulk inserts (no ORM overhead per row)
- A single plain file that is easy to back up or inspect
- The same file can be read by any tool (DB Browser, DBeaver, etc.)
- No Django migration needed — the schema is created by init_db()

The Django ORM is still used for the rest of the project (idea memory
API endpoints, admin, etc.). This module is a separate, purpose-built
index for one specific high-volume data source.

Schema
------
ba_search_terms
    id                   INTEGER PRIMARY KEY AUTOINCREMENT
    report_date          TEXT    -- "2026-05" (YYYY-MM), used to filter by period
    search_term          TEXT    -- normalised to lowercase, indexed
    search_frequency_rank INTEGER
    clicked_asin_1       TEXT    -- top clicked product ASIN
    clicked_title_1      TEXT
    click_share_1        REAL    -- fraction (0.0 – 1.0) of clicks going to ASIN 1
    conversion_share_1   REAL    -- fraction of conversions going to ASIN 1
    clicked_asin_2       TEXT
    clicked_title_2      TEXT
    click_share_2        REAL
    conversion_share_2   REAL
    clicked_asin_3       TEXT
    clicked_title_3      TEXT
    click_share_3        REAL
    conversion_share_3   REAL
    ingested_at          TEXT    -- ISO timestamp when this row was written

ba_ingestion_log
    id                   INTEGER PRIMARY KEY AUTOINCREMENT
    report_date          TEXT
    report_period        TEXT    -- MONTH / WEEK / DAY
    status               TEXT    -- success / error
    rows_inserted        INTEGER
    error_message        TEXT
    completed_at         TEXT    -- ISO timestamp
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    """
    Opens a SQLite connection with sensible performance settings.

    WAL mode (Write-Ahead Logging) allows reads and writes to happen
    concurrently. Without it, any write locks the entire database file.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row   # rows behave like dicts: row["search_term"]
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")  # faster writes, still crash-safe
    return conn


# ── Schema creation ───────────────────────────────────────────────────────────

def init_db(db_path: str) -> None:
    """
    Creates the SQLite database file and tables if they do not already exist.

    Safe to call on every startup — CREATE TABLE IF NOT EXISTS is idempotent.
    Also ensures the performance index on search_term exists.

    Parameters
    ----------
    db_path : str
        Absolute path to the SQLite file.
        The parent directory is created automatically if needed.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    with _connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ba_search_terms (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date           TEXT    NOT NULL,
                search_term           TEXT    NOT NULL,
                search_frequency_rank INTEGER,
                clicked_asin_1        TEXT,
                clicked_title_1       TEXT,
                click_share_1         REAL,
                conversion_share_1    REAL,
                clicked_asin_2        TEXT,
                clicked_title_2       TEXT,
                click_share_2         REAL,
                conversion_share_2    REAL,
                clicked_asin_3        TEXT,
                clicked_title_3       TEXT,
                click_share_3         REAL,
                conversion_share_3    REAL,
                ingested_at           TEXT    NOT NULL
            );

            -- This index is what makes keyword lookups fast during Tier 1 scoring.
            -- Without it, every lookup would scan the full table.
            CREATE INDEX IF NOT EXISTS idx_ba_search_term
                ON ba_search_terms (search_term);

            -- Composite index so filtering by report_date + search_term is fast
            CREATE INDEX IF NOT EXISTS idx_ba_date_term
                ON ba_search_terms (report_date, search_term);

            CREATE TABLE IF NOT EXISTS ba_ingestion_log (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date    TEXT    NOT NULL,
                report_period  TEXT    NOT NULL,
                status         TEXT    NOT NULL,
                rows_inserted  INTEGER DEFAULT 0,
                error_message  TEXT,
                completed_at   TEXT    NOT NULL
            );
        """)


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
        # Amazon sometimes sends percentages (12.5) instead of fractions (0.125)
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


def parse_report_tsv(tsv_text: str, report_date: str) -> list[dict]:
    """
    Parses the Brand Analytics Search Terms TSV report into a list of dicts
    ready to be inserted by insert_rows().

    Expected TSV columns (Amazon's standard format):
        Department Name | Search Term | Search Frequency Rank |
        #1 Clicked ASIN | #1 Product Title | #1 Click Share | #1 Conversion Share |
        #2 Clicked ASIN | #2 Product Title | #2 Click Share | #2 Conversion Share |
        #3 Clicked ASIN | #3 Product Title | #3 Click Share | #3 Conversion Share

    Parameters
    ----------
    tsv_text : str
        Raw TSV content from the downloaded report.
    report_date : str
        The reporting period label, e.g. "2026-05" (YYYY-MM).
        Stored alongside each row so you can query by period.

    Returns
    -------
    list[dict]
        One dict per data row, keys matching ba_search_terms columns.
    """
    lines = tsv_text.strip().splitlines()
    if not lines:
        return []

    # Skip the header row
    rows = []
    now = _now_iso()

    for line in lines[1:]:
        if not line.strip():
            continue

        cols = line.split("\t")

        # Pad to 15 columns in case trailing empties were stripped
        while len(cols) < 15:
            cols.append("")

        rows.append({
            "report_date":           report_date,
            "search_term":           cols[1].strip().lower(),  # always lowercase
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

def insert_rows(db_path: str, rows: list[dict]) -> int:
    """
    Bulk-inserts parsed report rows into ba_search_terms.

    Uses executemany() which is dramatically faster than one INSERT per row.
    For a 200k-row report, executemany() with WAL mode completes in ~2 seconds.
    One INSERT per row would take ~5 minutes.

    Before inserting, deletes any existing rows with the same report_date
    so re-running the ingestion for the same period is safe (idempotent).

    Parameters
    ----------
    db_path : str
        Path to the SQLite file (must already be initialised by init_db()).
    rows : list[dict]
        Parsed rows from parse_report_tsv().

    Returns
    -------
    int
        Number of rows inserted.
    """
    if not rows:
        return 0

    report_date = rows[0]["report_date"]

    with _connect(db_path) as conn:
        # Remove stale data for this period before re-inserting
        conn.execute(
            "DELETE FROM ba_search_terms WHERE report_date = ?",
            (report_date,)
        )

        conn.executemany(
            """
            INSERT INTO ba_search_terms (
                report_date, search_term, search_frequency_rank,
                clicked_asin_1, clicked_title_1, click_share_1, conversion_share_1,
                clicked_asin_2, clicked_title_2, click_share_2, conversion_share_2,
                clicked_asin_3, clicked_title_3, click_share_3, conversion_share_3,
                ingested_at
            ) VALUES (
                :report_date, :search_term, :search_frequency_rank,
                :clicked_asin_1, :clicked_title_1, :click_share_1, :conversion_share_1,
                :clicked_asin_2, :clicked_title_2, :click_share_2, :conversion_share_2,
                :clicked_asin_3, :clicked_title_3, :click_share_3, :conversion_share_3,
                :ingested_at
            )
            """,
            rows,
        )

    return len(rows)


# ── Lookup ────────────────────────────────────────────────────────────────────

def lookup(db_path: str, search_term: str, report_date: str = None) -> Optional[dict]:
    """
    Looks up a single keyword in the BA index.

    This is what the Tier 1 scorer calls for each idea keyword.
    It returns the most recent matching row.

    Parameters
    ----------
    db_path : str
        Path to the SQLite file.
    search_term : str
        Keyword to search for. Matched case-insensitively.
    report_date : str, optional
        If supplied, restricts the lookup to that reporting period.
        If None, returns the row from the most recent period available.

    Returns
    -------
    dict or None
        A dict with all ba_search_terms columns, or None if no match.
    """
    term = search_term.strip().lower()

    with _connect(db_path) as conn:
        if report_date:
            row = conn.execute(
                """
                SELECT * FROM ba_search_terms
                WHERE search_term = ? AND report_date = ?
                ORDER BY search_frequency_rank ASC
                LIMIT 1
                """,
                (term, report_date),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM ba_search_terms
                WHERE search_term = ?
                ORDER BY report_date DESC, search_frequency_rank ASC
                LIMIT 1
                """,
                (term,),
            ).fetchone()

    return dict(row) if row else None


def lookup_batch(db_path: str, keywords: list[str], report_date: str = None) -> dict:
    """
    Looks up multiple keywords in one query.

    More efficient than calling lookup() in a loop because a single
    SQL query with IN (...) replaces N separate queries.

    The Tier 1 scorer calls this when it has a list of keyword variants
    for one idea (e.g. ["bamboo travel mug", "bamboo insulated mug"]).

    Parameters
    ----------
    keywords : list[str]
        Keywords to look up.
    report_date : str, optional
        Restrict to a specific reporting period.

    Returns
    -------
    dict
        { keyword: row_dict_or_None, ... }
        Every input keyword is present as a key (value is None if not found).
    """
    if not keywords:
        return {}

    normalised = [k.strip().lower() for k in keywords]
    placeholders = ",".join("?" * len(normalised))

    with _connect(db_path) as conn:
        if report_date:
            rows = conn.execute(
                f"""
                SELECT * FROM ba_search_terms
                WHERE search_term IN ({placeholders}) AND report_date = ?
                ORDER BY report_date DESC, search_frequency_rank ASC
                """,
                normalised + [report_date],
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT * FROM ba_search_terms
                WHERE search_term IN ({placeholders})
                ORDER BY report_date DESC, search_frequency_rank ASC
                """,
                normalised,
            ).fetchall()

    # Group by search_term and keep only the best (first) row per term
    result = {k: None for k in normalised}
    for row in rows:
        term = row["search_term"]
        if result[term] is None:
            result[term] = dict(row)

    return result


def get_top_clicked_asins(db_path: str, search_term: str) -> list[str]:
    """
    Returns the list of top-clicked ASINs for a keyword (up to 3).

    The Tier 1 scorer uses this to know which products to pull
    product detail pages for — these are the real market leaders.

    Example
    -------
        asins = get_top_clicked_asins(db_path, "bamboo travel mug")
        # → ["B08XYZ123", "B07ABC456", "B09DEF789"]
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

    This gives a permanent audit trail: when was the last successful
    ingestion, how many rows were loaded, did any runs fail and why?

    Parameters
    ----------
    status : str
        "success" or "error"
    rows_inserted : int
        Number of rows successfully written to ba_search_terms.
    error_message : str
        The exception message if status == "error", otherwise empty.
    """
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ba_ingestion_log
                (report_date, report_period, status, rows_inserted, error_message, completed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (report_date, report_period, status, rows_inserted, error_message, _now_iso()),
        )


def get_latest_ingestion(db_path: str) -> Optional[dict]:
    """
    Returns the most recent successful ingestion log entry.

    Used by the API status endpoint to report when data was last refreshed.
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM ba_ingestion_log
            WHERE status = 'success'
            ORDER BY completed_at DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def get_db_stats(db_path: str) -> dict:
    """
    Returns a summary of what is currently in the database.
    Used by the status endpoint.
    """
    try:
        with _connect(db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM ba_search_terms").fetchone()[0]
            dates = conn.execute(
                "SELECT DISTINCT report_date FROM ba_search_terms ORDER BY report_date DESC"
            ).fetchall()
        return {
            "total_terms": total,
            "report_dates": [row[0] for row in dates],
        }
    except Exception:
        return {"total_terms": 0, "report_dates": []}
