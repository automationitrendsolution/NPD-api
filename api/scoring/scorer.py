"""
Tier 1 scorer — full pipeline orchestrator.

score_idea() is the single entry point. It:
    1. Gets or creates the idea in the memory store
    2. Checks cooldown (skips if too recent)
    3. Applies fast hard-kill rules (no scraping yet)
    4. Fetches Amazon SERP for the keyword
    5. Looks up the keyword in the Brand Analytics SQLite index
    6. Identifies the top competitor ASINs to investigate
    7. Fetches product detail pages for each competitor
    8. Runs all 5 deterministic sub-scorers
    9. Computes the composite score
   10. Saves all evidence + scores to the idea memory store
   11. Sets status to "scored" or "dismissed"
   12. Applies a cooldown if the score is below the minimum threshold

This module calls the scraping functions from api.search and api.product,
which means it spends real scraping credits. The gating at steps 2–3
ensures credits are only spent on ideas that are genuinely worth it.
"""

import time
from datetime import datetime, timezone

from django.conf import settings

from api.brand_analytics import db as ba_db
from api.memory import IdeaMemoryStore
from api.product.parser import parse_amazon_product
from api.product.scraper import fetch_amazon_product
from api.search.parser import parse_amazon_results
from api.search.scraper import fetch_amazon_search

from . import config as cfg
from .sub_scores import (
    compute_composite,
    score_demand,
    score_differentiation,
    score_economic,
    score_fit,
    score_saturation,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _select_competitor_asins(serp_results: list, ba_row: dict) -> list[str]:
    """
    Picks the best ASINs to fetch product detail pages for.

    Priority order:
    1. Top-clicked ASINs from Brand Analytics (most accurate market leaders)
    2. Organic (non-sponsored) top-ranked products from the SERP

    We deduplicate and cap at MAX_COMPETITOR_DETAILS to control scrape cost.
    """
    asins = []

    # BA top-clicked first (real purchase-intent leaders)
    if ba_row:
        for i in (1, 2, 3):
            asin = ba_row.get(f"clicked_asin_{i}")
            if asin and asin not in asins:
                asins.append(asin)

    # Fill remaining slots from top organic SERP results
    for product in serp_results:
        if product.get("sponsored"):
            continue
        asin = product.get("asin")
        if asin and asin not in asins:
            asins.append(asin)
        if len(asins) >= cfg.MAX_COMPETITOR_DETAILS:
            break

    return asins[:cfg.MAX_COMPETITOR_DETAILS]


def score_idea(
    keyword: str,
    idea_id: str = None,
    concept: str = "",
    source: str = "human_seeded",
    force_rescore: bool = False,
) -> dict:
    """
    Runs the full Tier 1 scoring pipeline for one product idea keyword.

    Parameters
    ----------
    keyword : str
        The Amazon search keyword to evaluate.
        Example: "bamboo travel mug"

    idea_id : str, optional
        If the idea already exists in the memory store, pass its idea_id
        to reuse the existing record.  If None, the store is searched by
        keyword; a new record is created if no match is found.

    concept : str, optional
        Human description of the product concept.  Only used when
        creating a new idea record.

    source : str, optional
        Entry route: "human_seeded", "autonomous", or "adjacency_mining".

    force_rescore : bool, optional
        If True, re-runs scoring even if the idea is already scored.
        Also bypasses the cooldown check.

    Returns
    -------
    dict with keys:
        status         : "scored" | "dismissed" | "skipped" | "error"
        idea_id        : str
        keyword        : str
        tier1_score    : int (0–100) or None
        tier1_scores   : dict of the five sub-scores
        skip_reason    : str  (present when status == "skipped")
        kill_reason    : str  (present when status == "dismissed")
        error          : str  (present when status == "error")
        duration_seconds: float
    """
    started = time.monotonic()
    keyword = keyword.strip().lower()

    store = IdeaMemoryStore(str(settings.IDEA_MEMORY_PATH))
    ba_db_path = str(settings.BA_DB_PATH)

    # ── Step 1: get or create the idea record ─────────────────────────────────
    if idea_id:
        idea = store.get(idea_id)
        if idea is None:
            return _error(keyword, None, f"No idea found with idea_id='{idea_id}'", started)
    else:
        idea = store.get_by_keyword(keyword)
        if idea is None:
            idea = store.create(keyword=keyword, concept=concept, source=source)

    idea_id = idea["idea_id"]

    # ── Step 2: cooldown check ────────────────────────────────────────────────
    if not force_rescore and store.is_on_cooldown(idea_id):
        cooldown_until = idea.get("cooldown_until", "unknown")
        return _skipped(keyword, idea_id, f"on cooldown until {cooldown_until}", started)

    # ── Step 3: already scored check ─────────────────────────────────────────
    if not force_rescore and idea.get("tier1_done"):
        return _skipped(keyword, idea_id, "already scored (pass force_rescore=True to re-run)", started)

    try:
        # ── Step 4: fast hard-kill check (free, no scraping) ─────────────────
        # We run the fit scorer with empty SERP/detail data.  It only checks
        # keyword patterns at this stage and returns score=0 if triggered.
        fast_fit = score_fit(keyword, [], [])
        if fast_fit["hard_killed"]:
            store.add_flag(idea_id, "hard_kill")
            store.update(
                idea_id,
                status="dismissed",
                tier1_done=True,
                tier1_at=_now_iso(),
                tier1_score=0,
                flags=idea.get("flags", []) + ["hard_kill"],
            )
            store.set_cooldown(idea_id, cfg.COOLDOWN_HOURS_DISMISSED)
            return {
                "status": "dismissed",
                "idea_id": idea_id,
                "keyword": keyword,
                "tier1_score": 0,
                "tier1_scores": {},
                "kill_reason": fast_fit["kill_reason"],
                "duration_seconds": round(time.monotonic() - started, 2),
            }

        # ── Step 5: fetch Amazon SERP ─────────────────────────────────────────
        print(f"[Scorer] Fetching SERP for '{keyword}'")
        serp_html = fetch_amazon_search(keyword, page=1)
        serp_results = parse_amazon_results(serp_html)
        print(f"[Scorer] Got {len(serp_results)} SERP products")

        if not serp_results:
            store.add_flag(idea_id, "empty_serp")

        # ── Step 6: Brand Analytics lookup ────────────────────────────────────
        ba_row = ba_db.lookup(ba_db_path, keyword)
        if ba_row is None:
            store.add_flag(idea_id, "no_ba_data")
            print(f"[Scorer] No BA data for '{keyword}'")
        else:
            print(f"[Scorer] BA rank={ba_row.get('search_frequency_rank')}")

        # ── Step 7: select competitor ASINs ───────────────────────────────────
        competitor_asins = _select_competitor_asins(serp_results, ba_row)
        print(f"[Scorer] Fetching detail pages for ASINs: {competitor_asins}")

        # ── Step 8: fetch competitor product detail pages ─────────────────────
        competitor_details = []
        for asin in competitor_asins:
            try:
                html = fetch_amazon_product(asin=asin)
                detail = parse_amazon_product(html)
                competitor_details.append(detail)
            except Exception as exc:
                print(f"[Scorer] Warning: could not fetch ASIN {asin}: {exc}")

        print(f"[Scorer] Fetched {len(competitor_details)} competitor detail pages")

        # ── Step 9: run sub-scorers ───────────────────────────────────────────
        demand_result        = score_demand(serp_results, ba_row)
        saturation_result    = score_saturation(serp_results, ba_row)
        diff_result          = score_differentiation(serp_results, competitor_details)
        fit_result           = score_fit(keyword, serp_results, competitor_details)
        economic_result      = score_economic(serp_results, competitor_details)

        sub_scores = {
            "demand":             demand_result["score"],
            "saturation":         saturation_result["score"],
            "differentiation":    diff_result["score"],
            "fit":                fit_result["score"],
            "economic_viability": economic_result["score"],
        }

        # ── Step 10: composite score ──────────────────────────────────────────
        composite = compute_composite(sub_scores)
        print(f"[Scorer] Composite={composite} | {sub_scores}")

        # ── Step 11: collect all flags ────────────────────────────────────────
        all_flags = list(set(
            idea.get("flags", [])
            + demand_result["flags"]
            + saturation_result["flags"]
            + diff_result["flags"]
            + fit_result["flags"]
            + economic_result["flags"]
        ))

        # ── Step 12: determine final status ───────────────────────────────────
        if fit_result["hard_killed"]:
            final_status = "dismissed"
        elif composite >= cfg.TIER1_MINIMUM_SCORE:
            final_status = "scored"
        else:
            final_status = "dismissed"

        # ── Step 13: build evidence snapshot ──────────────────────────────────
        # Everything saved here is the raw data used to produce the scores.
        # Future runs can re-score from this data without re-scraping.
        evidence = {
            "serp_results": serp_results,
            "competitor_asins": competitor_asins,
            "competitor_details": competitor_details,
            "price_band_low": economic_result["price_band_low"],
            "price_band_high": economic_result["price_band_high"],
            "review_count_median": _median_reviews(serp_results),
            "badge_count": sum(
                1 for p in serp_results
                if p.get("best_seller") or p.get("amazon_choice")
            ),
            "sponsored_ratio": round(
                sum(1 for p in serp_results if p.get("sponsored")) /
                max(len(serp_results), 1), 3
            ),
            "ba_row": ba_row,
        }

        # Score breakdown for audit
        score_breakdown = {
            "demand":             {
                "score": demand_result["score"],
                "components": demand_result["components"],
            },
            "saturation":         {
                "score": saturation_result["score"],
                "components": saturation_result["components"],
            },
            "differentiation":    {
                "score": diff_result["score"],
                "components": diff_result["components"],
            },
            "fit":                {
                "score": fit_result["score"],
                "components": fit_result.get("components", {}),
            },
            "economic_viability": {
                "score": economic_result["score"],
                "components": economic_result["components"],
            },
        }

        # ── Step 14: save to memory store ─────────────────────────────────────
        store.update(
            idea_id,
            status=final_status,
            tier1_done=True,
            tier1_at=_now_iso(),
            tier1_score=composite,
            tier1_scores=sub_scores,
            tier1_evidence=evidence,
            flags=all_flags,
        )

        # ── Step 15: apply cooldown if dismissed ──────────────────────────────
        if final_status == "dismissed":
            if fit_result["hard_killed"]:
                store.set_cooldown(idea_id, cfg.COOLDOWN_HOURS_DISMISSED)
            else:
                store.set_cooldown(idea_id, cfg.COOLDOWN_HOURS_LOW_SCORE)

        duration = round(time.monotonic() - started, 2)
        print(f"[Scorer] Done: status={final_status}, score={composite}, time={duration}s")

        result = {
            "status": final_status,
            "idea_id": idea_id,
            "keyword": keyword,
            "tier1_score": composite,
            "tier1_scores": sub_scores,
            "score_breakdown": score_breakdown,
            "flags": all_flags,
            "duration_seconds": duration,
        }

        if fit_result["hard_killed"]:
            result["kill_reason"] = fit_result["kill_reason"]

        if composite >= cfg.TIER1_5_THRESHOLD:
            result["eligible_for_tier15"] = True

        return result

    except Exception as exc:
        store.add_flag(idea_id, "scoring_error")
        return _error(keyword, idea_id, str(exc), started)


# ── Internal result helpers ───────────────────────────────────────────────────

def _median_reviews(serp_results: list):
    counts = [p["reviews"] for p in serp_results if (p.get("reviews") or 0) > 0]
    if not counts:
        return None
    import statistics
    return round(statistics.median(counts))


def _skipped(keyword, idea_id, reason, started):
    return {
        "status": "skipped",
        "idea_id": idea_id,
        "keyword": keyword,
        "tier1_score": None,
        "tier1_scores": {},
        "skip_reason": reason,
        "duration_seconds": round(time.monotonic() - started, 2),
    }


def _error(keyword, idea_id, message, started):
    print(f"[Scorer] ERROR for '{keyword}': {message}")
    return {
        "status": "error",
        "idea_id": idea_id,
        "keyword": keyword,
        "tier1_score": None,
        "tier1_scores": {},
        "error": message,
        "duration_seconds": round(time.monotonic() - started, 2),
    }
