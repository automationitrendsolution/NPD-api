"""
Django management command: run_tier3

Generates all pre-sourcing documents for an idea via three LLM calls:
  1. Product concept + simulated buyer poll
  2. Amazon listing draft (title, bullets, tagline, image brief)
  3. Manufacturer sourcing spec

Usage
-----
    python manage.py run_tier3 --idea-id <uuid>
    python manage.py run_tier3 --idea-id <uuid> --force
    python manage.py run_tier3 --all-pending
"""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.llm.tier3 import run_tier3
from api.memory import IdeaMemoryStore


class Command(BaseCommand):
    help = "Run Tier 3 pre-sourcing generation for one or all pending ideas."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--idea-id",
            type=str,
            help="Generate pre-sourcing documents for a single idea.",
        )
        group.add_argument(
            "--all-pending",
            action="store_true",
            help=(
                "Run for every idea with status='pre_sourcing' "
                "that has presourcing_done=False."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Re-run even if Tier 3 is already complete.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="Print result as JSON.",
        )

    def handle(self, *args, **options):
        force   = options["force"]
        as_json = options["json"]

        if options["idea_id"]:
            result = run_tier3(options["idea_id"], force=force)
            self._print_result(result, as_json)
            if result["status"] == "error":
                raise CommandError(result["error"])

        else:
            store = IdeaMemoryStore(str(settings.IDEA_MEMORY_PATH))
            pending = store.filter(presourcing_done=False)
            # Keep only ideas in pre_sourcing status
            pending = [i for i in pending if i.get("status") == "pre_sourcing"]

            if not pending:
                self.stdout.write(self.style.WARNING(
                    "No ideas in 'pre_sourcing' status with pending generation."
                ))
                return

            self.stdout.write(
                self.style.NOTICE(f"Processing {len(pending)} idea(s)...")
            )

            errors = 0
            for idea in pending:
                result = run_tier3(idea["idea_id"], force=force)
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
            data = result.get("presourcing_data", {})
            self.stdout.write(self.style.SUCCESS(
                f"\n✓ {keyword}\n"
                f"  Listing title : {(data.get('listing_title') or '')[:70]}\n"
                f"  Poll winner   : {result['presourcing_data'].get('buyer_poll_detail', {}).get('poll_winner', 'N/A')}\n"
                f"  Supplier terms: {', '.join((data.get('supplier_search_terms') or [])[:3])}\n"
                f"  Duration      : {result.get('duration_seconds')}s"
            ))
        elif status == "skipped":
            self.stdout.write(self.style.WARNING(
                f"\n⊘ {keyword}: {result.get('skip_reason')}"
            ))
        elif status == "error":
            self.stdout.write(self.style.ERROR(
                f"\n✗ {keyword}: {result.get('error')}"
            ))
