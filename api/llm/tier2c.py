"""
Tier 2C — Enhanced NPD Analysis.

Triggered when: reviews_scraped == True AND research_done == True
(Will run on partial data if either flag is False, noting what is missing.)

What this does
--------------
It takes ALL evidence collected so far — Tier 1 SERP data, Brand Analytics,
competitor product details, Amazon review corpus, and the AI deep research
report — and passes it to GPT-4o.

The LLM's job is SYNTHESIS ONLY.  It does not invent facts.  It reads
the evidence and organises it into a structured intelligence report:

    Voice-of-customer summary   ← from reviews
    Pain points & dealbreakers  ← from reviews
    Usage scenarios             ← from reviews
    Buyer motivations           ← from reviews + research
    End-user avatar             ← synthesised profile
    Buyer avatar                ← synthesised profile
    Feature response blueprint  ← maps features to pain points
    Differentiation strategy    ← based on the gap analysis
    Recommendation              ← Go / No-go / Conditional + reasoning

The output is saved to idea["tier2_analysis"] in the memory store
and tier2_done is set to True.
"""

import json
import statistics
import time
from datetime import datetime, timezone

from django.conf import settings

from api.memory import IdeaMemoryStore

from .client import MODEL_ANALYSIS, call_llm


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ── Prompt builder ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior Amazon product market analyst specialising in FBA opportunity research.

Your job is to synthesise market evidence into a structured intelligence report that a product sourcing team will use to decide whether to develop a new product.

STRICT RULES:
1. Only draw conclusions from the evidence provided in the user message.
2. Never invent, estimate, or fabricate market statistics, prices, review counts, or rankings.
3. If a piece of evidence is missing or thin, say so clearly rather than filling the gap with assumptions.
4. All analysis must be traceable to specific evidence (e.g. "Reviews frequently mention the lid leaking").
5. Return ONLY valid JSON matching the schema requested. No markdown fences, no commentary outside the JSON object.
"""


def _build_user_prompt(idea: dict) -> str:
    """
    Builds the full user prompt from an idea record.

    Pulls evidence from all completed tiers and formats it into a structured
    context block so the LLM can read and synthesise efficiently.
    """

    keyword = idea.get("keyword", "")
    concept = idea.get("concept", "")
    score   = idea.get("tier1_score", "N/A")
    scores  = idea.get("tier1_scores", {})
    ev      = idea.get("tier1_evidence", {})
    ba_row  = ev.get("ba_row") or {}

    # ── Tier 1 evidence summary ────────────────────────────────────────────────
    price_low  = ev.get("price_band_low",  "unknown")
    price_high = ev.get("price_band_high", "unknown")
    badge_count    = ev.get("badge_count", 0)
    sponsored_ratio = ev.get("sponsored_ratio", 0)
    median_reviews  = ev.get("review_count_median", "unknown")

    serp_products = ev.get("serp_results", [])
    top_products  = serp_products[:8]  # Keep prompt size manageable

    top_products_text = ""
    for i, p in enumerate(top_products, 1):
        top_products_text += (
            f"  {i}. {p.get('title', 'N/A')[:80]}\n"
            f"     Price: ${p.get('price', 'N/A')} | "
            f"Rating: {p.get('rating', 'N/A')} | "
            f"Reviews: {p.get('reviews', 'N/A')} | "
            f"Badges: {'Best Seller ' if p.get('best_seller') else ''}"
            f"{'Choice' if p.get('amazon_choice') else ''}\n"
        )

    # ── Brand Analytics data ───────────────────────────────────────────────────
    if ba_row:
        ba_text = (
            f"  Search frequency rank : {ba_row.get('search_frequency_rank', 'N/A')}\n"
            f"  #1 clicked ASIN       : {ba_row.get('clicked_asin_1', 'N/A')} "
            f"({ba_row.get('click_share_1', 0):.1%} click share, "
            f"{ba_row.get('conversion_share_1', 0):.1%} conversion share)\n"
            f"  #2 clicked ASIN       : {ba_row.get('clicked_asin_2', 'N/A')} "
            f"({ba_row.get('click_share_2', 0):.1%} click share)\n"
            f"  #3 clicked ASIN       : {ba_row.get('clicked_asin_3', 'N/A')} "
            f"({ba_row.get('click_share_3', 0):.1%} click share)\n"
        )
    else:
        ba_text = "  Not available for this keyword.\n"

    # ── Competitor product details ─────────────────────────────────────────────
    competitor_details = ev.get("competitor_details", [])
    competitor_text = ""
    for i, p in enumerate(competitor_details, 1):
        bullets = p.get("bullet_points") or []
        bullet_summary = " | ".join(bullets[:3]) if bullets else "N/A"
        competitor_text += (
            f"  Product {i}: {(p.get('title') or 'N/A')[:70]}\n"
            f"    Brand: {p.get('brand', 'N/A')} | "
            f"Price: ${p.get('price', 'N/A')} | "
            f"Rating: {p.get('rating', 'N/A')} | "
            f"Reviews: {p.get('review_count', 'N/A')}\n"
            f"    Key features: {bullet_summary}\n"
        )
    if not competitor_text:
        competitor_text = "  No competitor detail pages fetched.\n"

    # ── Review corpus ──────────────────────────────────────────────────────────
    review_data   = idea.get("review_data", {})
    review_pages  = review_data.get("review_pages", {})
    reviews_scraped = idea.get("reviews_scraped", False)

    review_text = ""
    total_reviews_shown = 0
    MAX_REVIEWS = 40  # Cap to manage prompt token size

    if review_pages:
        for asin, reviews in review_pages.items():
            review_text += f"\n  Reviews for ASIN {asin}:\n"
            for r in reviews[:15]:
                if total_reviews_shown >= MAX_REVIEWS:
                    break
                body = (r.get("body") or r.get("text") or r.get("content") or "")[:200]
                rating = r.get("rating") or r.get("stars") or "?"
                review_text += f"    [{rating}★] {body}\n"
                total_reviews_shown += 1
    elif not reviews_scraped:
        review_text = "  Review scraping has not been run yet for this idea.\n"
    else:
        review_text = "  Reviews were scraped but no review text was found.\n"

    # ── AI deep research report ────────────────────────────────────────────────
    research_report = idea.get("research_report", "")
    research_done   = idea.get("research_done", False)

    if research_report:
        # Truncate very long reports to keep prompt manageable
        research_section = research_report[:3000]
        if len(research_report) > 3000:
            research_section += "\n... [truncated for brevity]"
    elif not research_done:
        research_section = "AI deep research has not been run yet for this idea."
    else:
        research_section = "Research was run but produced no content."

    # ── Tier 1.5 enrichment ────────────────────────────────────────────────────
    tier15 = idea.get("tier15_data", {})
    if tier15 and idea.get("tier15_done"):
        tier15_text = (
            f"  Opportunity score        : {tier15.get('opportunity_score', 'N/A')}\n"
            f"  Competition strength     : {tier15.get('competition_strength', 'N/A')}\n"
            f"  Median competitor reviews: {tier15.get('median_review_count', 'N/A')}\n"
            f"  Launch keyword count     : {tier15.get('launch_keyword_count', 'N/A')}\n"
        )
    else:
        tier15_text = "  Tier 1.5 enrichment not yet run.\n"

    # ── Assemble full prompt ───────────────────────────────────────────────────
    return f"""
PRODUCT IDEA TO ANALYSE
=======================
Keyword : {keyword}
Concept : {concept or "Not specified"}
Status  : Tier 1 scored, awaiting deep analysis

TIER 1 SCORES
=============
Composite score     : {score}/100
  Demand            : {scores.get("demand", "N/A")}/100
  Ease of entry     : {scores.get("saturation", "N/A")}/100
  Differentiation   : {scores.get("differentiation", "N/A")}/100
  Fit               : {scores.get("fit", "N/A")}/100
  Economic viability: {scores.get("economic_viability", "N/A")}/100

Market snapshot:
  Price band        : ${price_low} – ${price_high}
  Median reviews    : {median_reviews}
  Badges on page 1  : {badge_count}
  Sponsored ratio   : {sponsored_ratio:.0%}

TOP SERP PRODUCTS (page 1)
==========================
{top_products_text or "  No SERP data available."}

COMPETITOR PRODUCT DETAILS
==========================
{competitor_text}

BRAND ANALYTICS DATA
====================
{ba_text}

TIER 1.5 EXTERNAL ENRICHMENT
=============================
{tier15_text}

CUSTOMER REVIEWS
================
{review_text or "  No reviews available."}

AI MARKET RESEARCH REPORT
==========================
{research_section}

---
TASK
====
Synthesise the above evidence and return a JSON object with EXACTLY these keys:

{{
  "voc_summary": "3-5 sentence summary of what customers say about this product category. Cite specific review themes.",

  "pain_points": [
    "Specific complaint or problem mentioned repeatedly in reviews (quote or paraphrase evidence)"
  ],

  "dealbreakers": [
    "Specific reason buyers return or leave negative reviews"
  ],

  "usage_scenarios": [
    "Real way buyers use this product, drawn from review language"
  ],

  "buyer_motivations": [
    "Core reason a buyer chooses this category over alternatives"
  ],

  "end_user_avatar": "2-3 sentence profile of the person who physically uses this product. Base on review language, not assumptions.",

  "buyer_avatar": "2-3 sentence profile of who makes the purchase decision (may differ from end user). E.g. a parent buying for a child.",

  "feature_blueprint": [
    {{
      "feature": "Feature name",
      "reason": "Which pain point or motivation this addresses",
      "priority": "must-have | nice-to-have | differentiator"
    }}
  ],

  "differentiation_strategy": "1-2 paragraph strategy for how a new entrant should position against current market leaders. Be specific about which competitor weaknesses to exploit and which buyer segment to target.",

  "recommendation": "Go | No-go | Conditional",
  "recommendation_reasoning": "1-2 paragraph explanation grounded in the evidence. If Conditional, state exactly what conditions must be met."
}}
""".strip()


# ── Main runner ────────────────────────────────────────────────────────────────

def run_tier2c(idea_id: str, force: bool = False) -> dict:
    """
    Runs the Tier 2C Enhanced NPD Analysis for an idea.

    Reads all available evidence from the idea memory store, sends it to
    GPT-4o for synthesis, and saves the structured result back to the store.

    Parameters
    ----------
    idea_id : str
        The idea_id of the idea to analyse.

    force : bool
        If True, re-runs even if tier2_done is already True.

    Returns
    -------
    dict with keys:
        status         : "complete" | "skipped" | "error"
        idea_id        : str
        keyword        : str
        analysis       : dict (the full Tier 2C output)
        duration_seconds: float
    """
    started = time.monotonic()
    store = IdeaMemoryStore(str(settings.IDEA_MEMORY_PATH))

    # ── Load the idea ──────────────────────────────────────────────────────────
    idea = store.get(idea_id)
    if idea is None:
        return {
            "status": "error",
            "idea_id": idea_id,
            "error": f"No idea found with idea_id='{idea_id}'",
            "duration_seconds": 0,
        }

    keyword = idea.get("keyword", "")

    # ── Guard: skip if already done ────────────────────────────────────────────
    if idea.get("tier2_done") and not force:
        return {
            "status": "skipped",
            "idea_id": idea_id,
            "keyword": keyword,
            "skip_reason": "Tier 2C already complete. Pass force=True to re-run.",
            "analysis": idea.get("tier2_analysis", {}),
            "duration_seconds": round(time.monotonic() - started, 2),
        }

    # ── Guard: must have passed Tier 1 ────────────────────────────────────────
    if not idea.get("tier1_done"):
        return {
            "status": "error",
            "idea_id": idea_id,
            "keyword": keyword,
            "error": "Tier 1 scoring must be completed before running Tier 2C.",
            "duration_seconds": round(time.monotonic() - started, 2),
        }

    # Log data availability so the user knows what the LLM worked with
    has_reviews  = idea.get("reviews_scraped", False)
    has_research = idea.get("research_done",   False)
    print(f"[Tier2C] Starting analysis for '{keyword}' "
          f"(reviews={'yes' if has_reviews else 'NO'}, "
          f"research={'yes' if has_research else 'NO'})")

    try:
        # ── Build prompt and call LLM ──────────────────────────────────────────
        user_prompt = _build_user_prompt(idea)

        print(f"[Tier2C] Calling {MODEL_ANALYSIS} ({len(user_prompt):,} chars in prompt)")
        analysis = call_llm(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=MODEL_ANALYSIS,
            temperature=0.3,
            json_mode=True,
            label="tier2c_analysis",
        )

        # ── Validate the response has required keys ────────────────────────────
        required_keys = {
            "voc_summary", "pain_points", "dealbreakers", "usage_scenarios",
            "buyer_motivations", "end_user_avatar", "buyer_avatar",
            "feature_blueprint", "differentiation_strategy",
            "recommendation", "recommendation_reasoning",
        }
        missing = required_keys - set(analysis.keys())
        if missing:
            # Not fatal — save what we have and flag the gap
            print(f"[Tier2C] Warning: LLM response missing keys: {missing}")

        # ── Save to memory store ───────────────────────────────────────────────
        store.update(
            idea_id,
            tier2_done=True,
            tier2_at=_now_iso(),
            status="shortlisted",          # promote status
            tier2_analysis={
                "voc_summary":              analysis.get("voc_summary", ""),
                "pain_points":              analysis.get("pain_points", []),
                "dealbreakers":             analysis.get("dealbreakers", []),
                "usage_scenarios":          analysis.get("usage_scenarios", []),
                "buyer_motivations":        analysis.get("buyer_motivations", []),
                "end_user_avatar":          analysis.get("end_user_avatar", ""),
                "buyer_avatar":             analysis.get("buyer_avatar", ""),
                "feature_blueprint":        analysis.get("feature_blueprint", []),
                "differentiation_strategy": analysis.get("differentiation_strategy", ""),
                "recommendation":           analysis.get("recommendation", ""),
                "recommendation_reasoning": analysis.get("recommendation_reasoning", ""),
            },
        )

        duration = round(time.monotonic() - started, 2)
        print(f"[Tier2C] Done in {duration}s. "
              f"Recommendation: {analysis.get('recommendation', 'N/A')}")

        return {
            "status": "complete",
            "idea_id": idea_id,
            "keyword": keyword,
            "recommendation": analysis.get("recommendation", ""),
            "analysis": analysis,
            "duration_seconds": duration,
        }

    except Exception as exc:
        duration = round(time.monotonic() - started, 2)
        print(f"[Tier2C] ERROR for '{keyword}': {exc}")
        return {
            "status": "error",
            "idea_id": idea_id,
            "keyword": keyword,
            "error": str(exc),
            "duration_seconds": duration,
        }
