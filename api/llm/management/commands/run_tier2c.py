"""
Django management command: run_tier2c

Runs the Tier 2C Enhanced NPD Analysis for a specific idea.
The idea must already have a Tier 1 score.  Review scraping and
AI deep research are optional but significantly improve output quality.

Usage
-----
    # Run analysis on a specific idea
    python manage.py run_tier2c --idea-id <uuid>

    # Re-run even if already complete
    python manage.py run_tier2c --idea-id <uuid> --force

    # Run for all shortlisted ideas that haven't had Tier 2C yet
    python manage.py run_tier2c --all-pending
"""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from api.llm.tier2c import run_tier2c
from api.memory import IdeaMemoryStore


class Command(BaseCommand):
    help = "Run Tier 2C Enhanced NPD Analysis (LLM synthesis) for one or all pending ideas."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--idea-id",
            type=str,
            help="Run analysis for a single idea by its idea_id.",
        )
        group.add_argument(
            "--all-pending",
            action="store_true",
            help=(
                "Run for every idea that has tier1_done=True but tier2_done=False. "
                "Processes ideas in creation order."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Re-run even if Tier 2C is already complete.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="Print result as JSON (useful for scripting).",
        )

    def handle(self, *args, **options):
        force   = options["force"]
        as_json = options["json"]

        if options["idea_id"]:
            result = run_tier2c(options["idea_id"], force=force)
            self._print_result(result, as_json)
            if result["status"] == "error":
                raise CommandError(result["error"])

        else:
            # Process all pending ideas
            store = IdeaMemoryStore(str(settings.IDEA_MEMORY_PATH))
            pending = store.filter(tier1_done=True, tier2_done=False) if not force else \
                      store.filter(tier1_done=True)

            if not pending:
                self.stdout.write(self.style.WARNING("No pending ideas found."))
                return

            self.stdout.write(
                self.style.NOTICE(f"Processing {len(pending)} idea(s)...")
            )

            errors = 0
            for idea in pending:
                result = run_tier2c(idea["idea_id"], force=force)
                self._print_result(result, as_json)
                if result["status"] == "error":
                    errors += 1

            if errors:
                self.stdout.write(
                    self.style.WARNING(f"\n{errors} idea(s) failed. Check logs above.")
                )

    def _print_result(self, result, as_json):
        if as_json:
            self.stdout.write(json.dumps(result, indent=2, default=str))
            return

        status  = result["status"]
        keyword = result.get("keyword", "?")

        if status == "complete":
            rec = result.get("recommendation", "N/A")
            colour = self.style.SUCCESS if "Go" in rec else self.style.WARNING
            self.stdout.write(colour(
                f"\n✓ {keyword}\n"
                f"  Recommendation: {rec}\n"
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
