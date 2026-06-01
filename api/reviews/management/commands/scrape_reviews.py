"""
Django management command: scrape_reviews

Tier 2A: Scrape Amazon customer reviews for shortlisted product ideas.

Usage
-----
    python manage.py scrape_reviews --idea-id <uuid>
    python manage.py scrape_reviews --all-pending
    python manage.py scrape_reviews --idea-id <uuid> --max-pages 5 --max-asins 4
    python manage.py scrape_reviews --idea-id <uuid> --force
    python manage.py scrape_reviews --all-pending --json
"""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.reviews.job import run_review_scraping
from api.memory import IdeaMemoryStore


class Command(BaseCommand):
    help = "Run Tier 2A review scraping for one or all pending shortlisted ideas."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--idea-id",
            type=str,
            help="Scrape reviews for a single idea by ID.",
        )
        group.add_argument(
            "--all-pending",
            action="store_true",
            help=(
                "Scrape reviews for every shortlisted idea "
                "where reviews_scraped=False."
            ),
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=3,
            help="Maximum review pages per ASIN (default: 3, ~30 reviews per ASIN).",
        )
        parser.add_argument(
            "--max-asins",
            type=int,
            default=3,
            help="Maximum competitor ASINs to scrape per idea (default: 3).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Re-scrape even if reviews are already collected.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="Print result(s) as JSON.",
        )

    def handle(self, *args, **options):
        force     = options["force"]
        as_json   = options["json"]
        max_pages = options["max_pages"]
        max_asins = options["max_asins"]

        if options["idea_id"]:
            result = run_review_scraping(
                options["idea_id"],
                max_pages=max_pages,
                max_asins=max_asins,
                force=force,
            )
            self._print_result(result, as_json)
            if result["status"] == "error":
                raise CommandError(result["error"])

        else:
            store = IdeaMemoryStore(str(settings.IDEA_MEMORY_PATH))
            pending = store.filter(status="shortlisted", reviews_scraped=False)

            if not pending:
                self.stdout.write(self.style.WARNING(
                    "No shortlisted ideas with pending review scraping."
                ))
                return

            self.stdout.write(
                self.style.NOTICE(f"Processing {len(pending)} idea(s)...")
            )

            errors = 0
            for idea in pending:
                result = run_review_scraping(
                    idea["idea_id"],
                    max_pages=max_pages,
                    max_asins=max_asins,
                    force=force,
                )
                self._print_result(result, as_json)
                if result["status"] == "error":
                    errors += 1

            if errors:
                self.stdout.write(
                    self.style.WARNING(f"\n{errors} idea(s) failed.")
                )

    def _print_result(self, result, as_json):
        if as_json:
            self.stdout.write(json.dumps(result, indent=2, default=str))
            return

        status  = result["status"]
        keyword = result.get("keyword", "?")

        if status == "complete":
            counts     = result.get("review_counts", {})
            counts_str = ", ".join(f"{asin}: {n}" for asin, n in counts.items())
            self.stdout.write(self.style.SUCCESS(
                f"\n✓ {keyword}\n"
                f"  ASINs scraped : {', '.join(result.get('asins_scraped', []))}\n"
                f"  Total reviews : {result.get('total_reviews', 0)}\n"
                f"  Per ASIN      : {counts_str}\n"
                f"  Duration      : {result.get('duration_seconds')}s"
            ))
            for w in result.get("warnings", []):
                self.stdout.write(self.style.WARNING(f"  Warning: {w}"))

        elif status == "skipped":
            self.stdout.write(self.style.WARNING(
                f"\n⊘ {keyword}: {result.get('skip_reason')}"
            ))

        elif status == "error":
            self.stdout.write(self.style.ERROR(
                f"\n✗ {keyword}: {result.get('error')}"
            ))
