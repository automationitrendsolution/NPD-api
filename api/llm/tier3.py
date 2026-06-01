"""
Tier 3 — Pre-Sourcing Validation and Document Generation.

Triggered when: a human moves the idea status to "pre_sourcing".

What this does
--------------
Uses three focused LLM calls (split for clarity and cost control) to
generate the full set of documents a sourcing team needs to brief
a manufacturer:

  Call 1 — Product Concept + Buyer Poll
      Defines exactly what product to build and tests it against the
      current market leader in a simulated buyer preference test.

  Call 2 — Amazon Listing Draft
      Generates a conversion-optimised title, 5 bullet points, a tagline,
      and an image shot list.

  Call 3 — Manufacturer Sourcing Spec
      Generates materials spec, dimension assumptions, packaging notes,
      compliance/safety requirements, quote volumes, supplier search terms,
      and lead-time expectations.

All three calls use gpt-4o-mini (fast model) because the task is
structured generation from a clear brief, not deep reasoning.

The combined output is saved to idea["presourcing_data"] and
presourcing_done is set to True.
"""

import time
from datetime import datetime, timezone

from django.conf import settings

from api.memory import IdeaMemoryStore

from .client import MODEL_FAST, call_llm


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ── Shared system prompt ───────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior Amazon product development consultant specialising in FBA product launches.

You generate precise, actionable documents for product sourcing teams.

RULES:
1. Base all outputs on the product intelligence provided. Do not invent market data.
2. Be specific: concrete materials, real dimensions, actual Amazon keyword language.
3. Write bullet points in Amazon's proven style: lead with the benefit, follow with the feature.
4. Return ONLY valid JSON matching the exact schema requested. No markdown, no commentary outside JSON.
"""


# ── Evidence builder (shared across all 3 calls) ──────────────────────────────

def _build_evidence_block(idea: dict) -> str:
    """
    Builds a compact evidence summary used as context in all three Tier 3 calls.
    Pulls from Tier 1 evidence and Tier 2C analysis.
    """
    keyword   = idea.get("keyword", "")
    concept   = idea.get("concept", "")
    ev        = idea.get("tier1_evidence", {})
    analysis  = idea.get("tier2_analysis", {})
    scores    = idea.get("tier1_scores", {})

    price_low  = ev.get("price_band_low",  "unknown")
    price_high = ev.get("price_band_high", "unknown")

    # Top competitor titles
    serp = ev.get("serp_results", [])
    top_titles = [p.get("title", "")[:70] for p in serp[:5] if p.get("title")]
    titles_text = "\n  ".join(f"- {t}" for t in top_titles) if top_titles else "Not available"

    # Tier 2C intelligence
    pain_points = analysis.get("pain_points", [])
    pain_text   = "\n  ".join(f"- {p}" for p in pain_points[:6]) if pain_points else "Not available"

    diff_strategy = analysis.get("differentiation_strategy", "Not available")
    feature_bp    = analysis.get("feature_blueprint", [])
    features_text = "\n  ".join(
        f"- {f.get('feature', '')} [{f.get('priority', '')}]: {f.get('reason', '')}"
        for f in feature_bp[:8]
    ) if feature_bp else "Not available"

    end_user  = analysis.get("end_user_avatar", "Not specified")
    buyer     = analysis.get("buyer_avatar",    "Not specified")
    recommendation = analysis.get("recommendation", "")
    reasoning      = analysis.get("recommendation_reasoning", "")

    return f"""
PRODUCT IDEA
============
Keyword         : {keyword}
Concept note    : {concept or "None provided"}
Recommendation  : {recommendation} — {reasoning[:200] if reasoning else "N/A"}

MARKET CONTEXT
==============
Price band      : ${price_low} – ${price_high}
Demand score    : {scores.get("demand", "N/A")}/100
Ease of entry   : {scores.get("saturation", "N/A")}/100
Differentiation : {scores.get("differentiation", "N/A")}/100
Economics       : {scores.get("economic_viability", "N/A")}/100

Top 5 competitor titles:
  {titles_text}

CUSTOMER INTELLIGENCE (from Tier 2C)
=====================================
Top pain points customers experience:
  {pain_text}

End-user avatar : {end_user}
Buyer avatar    : {buyer}

Differentiation strategy:
  {diff_strategy[:500] if diff_strategy else "Not available"}

Recommended feature set:
  {features_text}
""".strip()


# ── Call 1: Product Concept + Buyer Poll ──────────────────────────────────────

def _generate_concept_and_poll(idea: dict) -> dict:
    """
    Call 1 of 3.

    Generates:
    - A precise 1-paragraph product concept definition
    - A simulated buyer preference poll (our product vs. the leading competitor)

    The buyer poll works like this: the LLM is given both product descriptions
    and asked to evaluate from the perspective of the target buyer avatar,
    giving a preference and the key reasons why.
    """
    ev = idea.get("tier1_evidence", {})
    analysis = idea.get("tier2_analysis", {})

    # Get the leading competitor's title from BA or SERP
    ba_row = ev.get("ba_row") or {}
    serp   = ev.get("serp_results", [])
    top_organics = [p for p in serp if not p.get("sponsored")]

    competitor_title = ""
    competitor_price = ""
    if ba_row.get("clicked_asin_1"):
        # Find the title from competitor details if available
        details = ev.get("competitor_details", [])
        if details:
            competitor_title = details[0].get("title", "")
            competitor_price = str(details[0].get("price", ""))

    if not competitor_title and top_organics:
        competitor_title = top_organics[0].get("title", "")
        competitor_price = str(top_organics[0].get("price", ""))

    evidence_block = _build_evidence_block(idea)

    user_prompt = f"""
{evidence_block}

LEADING COMPETITOR
==================
Title : {competitor_title or "Unknown"}
Price : ${competitor_price or "Unknown"}

---
TASK — return JSON with EXACTLY these keys:

{{
  "product_concept": "One precise paragraph defining the product: what it is, who it is for, what problem it solves, and what makes it better than the current market leader. Be specific about materials, use case, and target customer.",

  "buyer_poll_setup": "One sentence describing how the poll was framed",

  "our_product_description": "3-sentence description of our proposed product written from a marketing perspective",

  "competitor_description": "3-sentence objective description of the leading competitor product",

  "poll_winner": "our_product | competitor | tie",

  "poll_reasoning": "2-3 sentences explaining which product the target buyer would prefer and why, based on the pain points and buyer avatar above",

  "poll_score": {{
    "our_product": 0,
    "competitor": 0,
    "note": "out of 10, from the perspective of the buyer avatar"
  }}
}}
""".strip()

    return call_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=MODEL_FAST,
        temperature=0.4,
        json_mode=True,
        label="tier3_concept_poll",
    )


# ── Call 2: Amazon Listing Draft ──────────────────────────────────────────────

def _generate_listing(idea: dict, concept_result: dict) -> dict:
    """
    Call 2 of 3.

    Generates a conversion-optimised Amazon listing:
    - Title (200 chars, keyword-first)
    - 5 bullet points (benefit-led, Amazon style)
    - Tagline (for packaging / brand copy)
    - Image shot list (what photos to brief to a photographer)
    """
    evidence_block = _build_evidence_block(idea)
    product_concept = concept_result.get("product_concept", "")

    user_prompt = f"""
{evidence_block}

PRODUCT CONCEPT (already defined)
===================================
{product_concept}

---
TASK — Write an Amazon listing for this product. Return JSON with EXACTLY these keys:

{{
  "listing_title": "Amazon product title. Max 200 characters. Lead with the primary keyword. Include brand placeholder [BRAND], key material, size/quantity if relevant, and primary use case. Do NOT use ALL CAPS or special characters.",

  "bullet_points": [
    "Bullet 1: Lead with the biggest customer benefit in 5-8 words (CAPS), then explain the feature that delivers it. 150-200 chars.",
    "Bullet 2: Address the #1 pain point from reviews directly. 150-200 chars.",
    "Bullet 3: Differentiation claim — what makes this better than competitors. 150-200 chars.",
    "Bullet 4: Use case / lifestyle benefit that connects with the buyer avatar. 150-200 chars.",
    "Bullet 5: Trust signal — quality, warranty, compatibility, or ease of use. 150-200 chars."
  ],

  "tagline": "One punchy tagline for packaging or brand marketing. Max 10 words.",

  "image_shot_list": [
    {{
      "shot": "Shot number and name, e.g. 'Shot 1: Hero product'",
      "description": "What exactly to show — angle, background, props, context",
      "purpose": "What this shot communicates to the buyer"
    }}
  ]
}}
""".strip()

    return call_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=MODEL_FAST,
        temperature=0.5,   # Slightly higher for creative copy
        json_mode=True,
        label="tier3_listing",
    )


# ── Call 3: Manufacturer Sourcing Spec ────────────────────────────────────────

def _generate_sourcing_spec(idea: dict, concept_result: dict) -> dict:
    """
    Call 3 of 3.

    Generates the full manufacturer brief:
    - Materials spec
    - Dimension assumptions
    - Packaging notes
    - Compliance / safety requirements
    - Quote volume assumptions
    - Supplier search terms
    - Lead-time assumptions
    """
    evidence_block   = _build_evidence_block(idea)
    product_concept  = concept_result.get("product_concept", "")
    ev               = idea.get("tier1_evidence", {})
    price_low        = ev.get("price_band_low",  15)
    price_high       = ev.get("price_band_high", 50)

    user_prompt = f"""
{evidence_block}

PRODUCT CONCEPT
===============
{product_concept}

Retail price target: ${price_low} – ${price_high}
Target COGS: 33% of retail price = ${round((float(price_low or 15) + float(price_high or 50)) / 2 * 0.33, 2)} per unit

---
TASK — Generate a manufacturer sourcing specification. Return JSON with EXACTLY these keys:

{{
  "materials_spec": "Specific materials list with quality notes. E.g. 'Food-grade silicone (BPA-free), 304 stainless steel inner, PP plastic lid'. Be precise — this goes directly to a factory.",

  "dimensions_assumptions": "Estimated product dimensions and weight. Base on competitor products and the price point. E.g. '280ml capacity, approx 18cm height × 8cm diameter, target weight <300g'.",

  "packaging_notes": "Retail packaging requirements: box type, insert card, colour scheme guidance, certification marks needed, language requirements.",

  "compliance_notes": "Relevant safety standards and certifications for the US market. E.g. 'CPSC compliance, California Prop 65, ASTM F963 if applicable, FCC if electronic. Note any FDA requirements.'",

  "quote_volume_assumptions": "Recommended MOQ and volumes for initial quote. Include the logic. E.g. 'Request quotes at 500 / 1000 / 2000 units. Initial order likely 500 units to test market.'",

  "supplier_search_terms": [
    "Alibaba/Global Sources search term 1",
    "Alibaba/Global Sources search term 2",
    "Alibaba/Global Sources search term 3",
    "Trade show category to target"
  ],

  "lead_time_assumptions": "Expected production + shipping lead time. Split into: sample lead time, bulk production lead time, sea freight to FBA warehouse. Include seasonal caveats (Chinese New Year, etc.)."
}}
""".strip()

    return call_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        model=MODEL_FAST,
        temperature=0.2,   # Low temp — this is a technical spec, not creative
        json_mode=True,
        label="tier3_sourcing_spec",
    )


# ── Main runner ────────────────────────────────────────────────────────────────

def run_tier3(idea_id: str, force: bool = False) -> dict:
    """
    Runs the full Tier 3 pre-sourcing generation for an idea.

    Makes three sequential LLM calls:
      1. Product concept + buyer poll
      2. Amazon listing draft
      3. Manufacturer sourcing spec

    Each call's output feeds into the next, so concept_result goes into
    the listing prompt and sourcing spec prompt as context.

    Parameters
    ----------
    idea_id : str
        The idea_id in the memory store.

    force : bool
        If True, re-runs even if presourcing_done is already True.

    Returns
    -------
    dict with keys:
        status          : "complete" | "skipped" | "error"
        idea_id         : str
        keyword         : str
        presourcing_data: dict (all three outputs combined)
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
    if idea.get("presourcing_done") and not force:
        return {
            "status": "skipped",
            "idea_id": idea_id,
            "keyword": keyword,
            "skip_reason": "Tier 3 already complete. Pass force=True to re-run.",
            "presourcing_data": idea.get("presourcing_data", {}),
            "duration_seconds": round(time.monotonic() - started, 2),
        }

    # ── Guard: must have Tier 1 ────────────────────────────────────────────────
    if not idea.get("tier1_done"):
        return {
            "status": "error",
            "idea_id": idea_id,
            "keyword": keyword,
            "error": "Tier 1 scoring must be completed before Tier 3.",
            "duration_seconds": round(time.monotonic() - started, 2),
        }

    # Tier 2 is recommended but not hard-required
    if not idea.get("tier2_done"):
        print(f"[Tier3] Warning: Tier 2C analysis not complete for '{keyword}'. "
              f"Output quality will be lower without review/research data.")

    print(f"[Tier3] Starting pre-sourcing generation for '{keyword}'")

    try:
        # ── Call 1: Product concept + buyer poll ───────────────────────────────
        print("[Tier3] Call 1/3: product concept + buyer poll")
        concept_result = _generate_concept_and_poll(idea)

        # ── Call 2: Listing draft ──────────────────────────────────────────────
        print("[Tier3] Call 2/3: Amazon listing draft")
        listing_result = _generate_listing(idea, concept_result)

        # ── Call 3: Sourcing spec ──────────────────────────────────────────────
        print("[Tier3] Call 3/3: manufacturer sourcing spec")
        spec_result = _generate_sourcing_spec(idea, concept_result)

        # ── Assemble the combined presourcing_data payload ─────────────────────
        presourcing_data = {
            # From Call 1
            "product_concept":      concept_result.get("product_concept", ""),
            "buyer_poll_result":    (
                f"{concept_result.get('poll_winner', '')} — "
                f"{concept_result.get('poll_reasoning', '')}"
            ),
            "buyer_poll_detail":    concept_result,

            # From Call 2
            "listing_title":   listing_result.get("listing_title", ""),
            "bullet_points":   listing_result.get("bullet_points", []),
            "tagline":         listing_result.get("tagline", ""),
            "image_shot_list": listing_result.get("image_shot_list", []),

            # From Call 3
            "materials_spec":            spec_result.get("materials_spec", ""),
            "dimensions_assumptions":    spec_result.get("dimensions_assumptions", ""),
            "packaging_notes":           spec_result.get("packaging_notes", ""),
            "compliance_notes":          spec_result.get("compliance_notes", ""),
            "quote_volume_assumptions":  spec_result.get("quote_volume_assumptions", ""),
            "supplier_search_terms":     spec_result.get("supplier_search_terms", []),
            "lead_time_assumptions":     spec_result.get("lead_time_assumptions", ""),
        }

        # ── Save to memory store ───────────────────────────────────────────────
        store.update(
            idea_id,
            presourcing_done=True,
            presourcing_at=_now_iso(),
            status="pre_sourcing",
            presourcing_data=presourcing_data,
        )

        duration = round(time.monotonic() - started, 2)
        print(f"[Tier3] Done in {duration}s for '{keyword}'")

        return {
            "status": "complete",
            "idea_id": idea_id,
            "keyword": keyword,
            "presourcing_data": presourcing_data,
            "duration_seconds": duration,
        }

    except Exception as exc:
        duration = round(time.monotonic() - started, 2)
        print(f"[Tier3] ERROR for '{keyword}': {exc}")
        return {
            "status": "error",
            "idea_id": idea_id,
            "keyword": keyword,
            "error": str(exc),
            "duration_seconds": duration,
        }
