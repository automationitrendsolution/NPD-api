"""
Django management command: ingest_brand_analytics

Usage
-----
    # Ingest the previous full calendar month (most common)
    python manage.py ingest_brand_analytics

    # Ingest a specific month
    python manage.py ingest_brand_analytics --start-date 2026-04-01 --end-date 2026-04-30

    # Ingest by week
    python manage.py ingest_brand_analytics --start-date 2026-05-26 --end-date 2026-06-01 --period WEEK

    # Dry run: parse only, do not write to the database
    python manage.py ingest_brand_analytics --dry-run

Django management commands live in management/commands/ and are discovered
automatically when the app is in INSTALLED_APPS. They appear in:
    python manage.py help
"""

from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.brand_analytics.ingestion import run_ingestion


def _last_full_month():
    """
    Returns (start_date, end_date, label) for the most recently completed
    calendar month in ISO 8601 format.

    Example: called in June 2026 → returns May 2026 window.
    """
    today = datetime.now(timezone.utc)
    # First day of this month
    first_this_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # Last day of last month = day before the 1st of this month
    last_day_prev = first_this_month - timedelta(days=1)
    # First day of last month
    first_day_prev = last_day_prev.replace(day=1)

    start = first_day_prev.strftime("%Y-%m-%dT00:00:00Z")
    end   = last_day_prev.strftime("%Y-%m-%dT23:59:59Z")
    label = first_day_prev.strftime("%Y-%m")
    return start, end, label


class Command(BaseCommand):
    help = (
        "Ingest a Brand Analytics Search Terms report from SP-API into the local "
        "SQLite index. By default, ingests the previous full calendar month."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=str,
            default=None,
            help=(
                "Report data start date, YYYY-MM-DD or full ISO 8601. "
                "Defaults to the first day of the previous calendar month."
            ),
        )
        parser.add_argument(
            "--end-date",
            type=str,
            default=None,
            help=(
                "Report data end date, YYYY-MM-DD or full ISO 8601. "
                "Defaults to the last day of the previous calendar month."
            ),
        )
        parser.add_argument(
            "--period",
            type=str,
            default="MONTH",
            choices=["MONTH", "WEEK", "DAY"],
            help="Report aggregation period. Default: MONTH.",
        )
        parser.add_argument(
            "--label",
            type=str,
            default=None,
            help=(
                "Human-readable label stored with each row, e.g. '2026-05'. "
                "Defaults to YYYY-MM of the start date."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help=(
                "Request the report and download it, but do NOT write to the database. "
                "Useful for testing credentials and connectivity."
            ),
        )

    def handle(self, *args, **options):
        # Resolve dates
        start_date = options["start_date"]
        end_date   = options["end_date"]
        period     = options["period"]
        label      = options["label"]
        dry_run    = options["dry_run"]

        if not start_date or not end_date:
            default_start, default_end, default_label = _last_full_month()
            start_date = start_date or default_start
            end_date   = end_date   or default_end
            label      = label      or default_label

        # Normalise YYYY-MM-DD to full ISO 8601 if needed
        if len(start_date) == 10:
            start_date = start_date + "T00:00:00Z"
        if len(end_date) == 10:
            end_date = end_date + "T23:59:59Z"

        db_path = str(settings.BA_DB_PATH)

        self.stdout.write(
            self.style.NOTICE(
                f"\nBrand Analytics ingestion\n"
                f"  Period   : {start_date} → {end_date}\n"
                f"  Agg      : {period}\n"
                f"  DB path  : {db_path}\n"
                f"  Dry run  : {dry_run}\n"
            )
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "--dry-run: will download report but NOT write to database."
                )
            )

        result = run_ingestion(
            db_path=db_path,
            data_start_date=start_date,
            data_end_date=end_date,
            report_period=period,
            report_date_label=label,
        )

        if result["status"] == "success":
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Ingestion complete\n"
                    f"  Rows inserted : {result['rows_inserted']:,}\n"
                    f"  Report ID     : {result['report_id']}\n"
                    f"  Duration      : {result['duration_seconds']}s\n"
                )
            )
        else:
            raise CommandError(
                f"Ingestion failed after {result['duration_seconds']}s:\n"
                f"{result.get('error', 'Unknown error')}"
            )
