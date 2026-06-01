"""
Django management command: score_idea

Runs the full Tier 1 scoring pipeline for one product keyword.
Useful for testing a single idea from the command line or triggering
a re-score on an existing idea.

Usage
-----
    # Score a new keyword
    python manage.py score_idea --keyword "bamboo travel mug"

    # Score with a concept note
    python manage.py score_idea --keyword "silicone baby bib" --concept "BPA-free, self-feeding starter bib"

    # Re-score an already-scored idea (bypasses cooldown)
    python manage.py score_idea --keyword "bamboo travel mug" --force

    # Score a specific existing idea by its memory store ID
    python manage.py score_idea --idea-id abc-123-def

    # Run as an autonomous discovery idea (different source label)
    python manage.py score_idea --keyword "travel pillow" --source autonomous
"""

import json

from django.core.management.base import BaseCommand, CommandError

from api.scoring.scorer import score_idea
from api.scoring import config as cfg


class Command(BaseCommand):
    help = "Run Tier 1 scoring for a product keyword. Fetches SERP, looks up Brand Analytics, computes scores, and saves to idea memory."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keyword", "-k",
            type=str,
            default=None,
            help="Amazon search keyword to score, e.g. 'bamboo travel mug'.",
        )
        parser.add_argument(
            "--idea-id",
            type=str,
            default=None,
            help="Score an existing idea by its idea_id from the memory store.",
        )
        parser.add_argument(
            "--concept",
            type=str,
            default="",
            help="Optional product concept description (used when creating a new idea record).",
        )
        parser.add_argument(
            "--source",
            type=str,
            default="human_seeded",
            choices=["human_seeded", "autonomous", "adjacency_mining"],
            help="How the idea entered the pipeline. Default: human_seeded.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Re-score even if already scored or on cooldown.",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="Print the full result as JSON (useful for scripting).",
        )

    def handle(self, *args, **options):
        keyword  = options["keyword"]
        idea_id  = options["idea_id"]
        concept  = options["concept"]
        source   = options["source"]
        force    = options["force"]
        as_json  = options["json"]

        if not keyword and not idea_id:
            raise CommandError("Provide either --keyword or --idea-id.")

        label = keyword or idea_id
        self.stdout.write(self.style.NOTICE(f"\nScoring: {label}"))

        result = score_idea(
            keyword=keyword or "",
            idea_id=idea_id,
            concept=concept,
            source=source,
            force_rescore=force,
        )

        if as_json:
            self.stdout.write(json.dumps(result, indent=2, default=str))
            return

        status = result["status"]
        score  = result.get("tier1_score")

        if status == "scored":
            colour = self.style.SUCCESS if score >= cfg.TIER1_TASK_THRESHOLD else self.style.WARNING
            self.stdout.write(colour(
                f"\n✓ Scored — composite: {score}/100\n"
            ))
            sub = result.get("tier1_scores", {})
            for name, val in sub.items():
                bar = "█" * (val // 10) + "░" * (10 - val // 10)
                self.stdout.write(f"  {name:<22} {bar}  {val}")

            flags = result.get("flags", [])
            if flags:
                self.stdout.write(f"\n  Flags: {', '.join(flags)}")

            if result.get("eligible_for_tier15"):
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n  ★ Score ≥{cfg.TIER1_5_THRESHOLD} → eligible for Tier 1.5 enrichment"
                    )
                )

        elif status == "dismissed":
            self.stdout.write(self.style.ERROR(
                f"\n✗ Dismissed (score={score})\n"
                f"  Reason: {result.get('kill_reason', 'score below minimum')}"
            ))

        elif status == "skipped":
            self.stdout.write(self.style.WARNING(
                f"\n⊘ Skipped: {result.get('skip_reason')}"
            ))

        elif status == "error":
            raise CommandError(
                f"Scoring failed for '{label}':\n{result.get('error')}"
            )

        self.stdout.write(
            f"\n  idea_id  : {result.get('idea_id')}\n"
            f"  duration : {result.get('duration_seconds')}s\n"
        )
