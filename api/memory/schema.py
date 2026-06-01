"""
Idea record schema.

Every idea stored in the memory file follows this exact structure.
build_default_idea() creates a blank record with all fields set to
their safe starting values. Nothing is left undefined so every
downstream reader can trust the keys exist.
"""

import uuid
from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def build_default_idea(keyword: str, concept: str = "", source: str = "human_seeded") -> dict:
    """
    Returns a fresh idea record ready to be saved to the memory store.

    Parameters
    ----------
    keyword : str
        The Amazon search keyword that represents this idea.
        Example: "bamboo travel mug"

    concept : str
        Optional free-text product concept description written by a human.
        Example: "A lightweight bamboo-lined travel mug for eco-conscious commuters"

    source : str
        How the idea entered the pipeline.
        - "human_seeded"    → a person manually added it to the task board
        - "autonomous"      → the system generated it from Brand Analytics data
        - "adjacency_mining"→ discovered from market-basket adjacency data
    """

    return {
        # ── Identity ──────────────────────────────────────────────────────────
        "idea_id": str(uuid.uuid4()),       # Unique ID, never changes after creation
        "keyword": keyword.strip().lower(), # Normalised so "Bamboo Mug" == "bamboo mug"
        "concept": concept.strip(),         # Human description (can be empty)
        "source": source,                   # Entry route (see docstring above)

        # ── Timestamps ────────────────────────────────────────────────────────
        "created_at": _now_iso(),           # Set once at creation, never updated
        "updated_at": _now_iso(),           # Refreshed on every update() call

        # ── Workflow status ───────────────────────────────────────────────────
        # Valid transitions:
        #   new → scored → shortlisted → pre_sourcing → approved
        #                                              → dismissed
        # A human must manually move an idea from scored→shortlisted and
        # shortlisted→pre_sourcing. The system handles every other transition.
        "status": "new",

        # ── Rate-limiting / cooldown ───────────────────────────────────────────
        # If an idea scores poorly, the system sets this to a future ISO
        # timestamp. The scorer skips the idea until the cooldown expires,
        # preventing wasted scrape credits on re-evaluating the same dead end.
        "cooldown_until": None,

        # ── Flags ─────────────────────────────────────────────────────────────
        # A list of string flags set by the pipeline, e.g.:
        #   "hard_kill"       → deterministic rule killed this before scoring
        #   "low_demand"      → demand score below minimum threshold
        #   "high_saturation" → too many strong competitors
        #   "no_ba_data"      → no Brand Analytics match found for the keyword
        "flags": [],

        # ── Task board ────────────────────────────────────────────────────────
        # ID of the corresponding card/task in the human-facing task board
        # (Linear / Notion / ClickUp etc.). Null until the task is created.
        "task_board_id": None,

        # ── Tier 1 — Market scan + scoring ───────────────────────────────────
        "tier1_done": False,
        "tier1_at": None,

        # Overall Tier 1 score (0–100). Composite of the five sub-scores below.
        "tier1_score": None,

        # Sub-scores, each 0–100, computed separately so they are individually
        # auditable. Stored as a nested dict, not flat fields, to keep the
        # top-level idea record readable.
        "tier1_scores": {
            "demand": None,           # How much genuine search demand exists
            "saturation": None,       # How crowded and entrenched the competition is
            "differentiation": None,  # Whether there is a gap to exploit
            "fit": None,              # Category / material / supply-chain plausibility
            "economic_viability": None  # Does the unit economics make sense
        },

        # Raw evidence collected during Tier 1. Stored separately from scores
        # so the scorer can be re-run on the same data without re-scraping.
        "tier1_evidence": {
            "serp_results": [],         # List of products from the Amazon SERP
            "competitor_asins": [],     # ASINs selected for deeper analysis
            "competitor_details": [],   # Product detail page data per ASIN
            "ba_search_terms": [],      # Matching Brand Analytics rows
            "price_band_low": None,     # Lowest organic price seen in SERP
            "price_band_high": None,    # Highest organic price seen in SERP
            "review_count_median": None,# Median review count across top competitors
            "badge_count": 0,           # Number of Best Seller / Choice badges on page 1
            "sponsored_ratio": 0.0,     # Fraction of SERP slots that are sponsored
        },

        # ── Tier 1.5 — External market enrichment ────────────────────────────
        # Runs only for ideas that score above the Tier 1.5 threshold.
        "tier15_done": False,
        "tier15_at": None,
        "tier15_data": {
            "opportunity_score": None,  # Score from external market tool
            "competitor_benchmarks": [],
            "median_review_count": None,
            "keyword_opportunities": [],
            "launch_keyword_count": None,
            "competition_strength": None,
        },

        # ── Tier 2A — Review scraping ─────────────────────────────────────────
        # Triggered when a human moves the idea to "shortlisted".
        "reviews_scraped": False,
        "reviews_scraped_at": None,
        "review_data": {
            "products_reviewed": [],    # ASINs whose reviews were scraped
            "review_pages": {},         # { asin: [list of review dicts] }
            "pain_points": [],          # Recurring complaints extracted from text
            "use_cases": [],            # How buyers actually use the product
            "feature_requests": [],     # Things buyers wish the product had
            "buyer_objections": [],     # Reasons buyers hesitate or return
        },

        # ── Tier 2B — AI deep research ────────────────────────────────────────
        "research_done": False,
        "research_done_at": None,
        "research_report": "",          # Full Markdown report from AI research tool
        "research_summary": {
            "market_context": "",
            "competitor_positioning": "",
            "customer_segments": [],
            "trend_signals": [],
            "risks": [],
            "differentiation_angles": [],
            "strategic_recommendation": "",
        },

        # ── Tier 2C — Enhanced NPD analysis ──────────────────────────────────
        # Runs only when both 2A and 2B are complete.
        "tier2_done": False,
        "tier2_at": None,
        "tier2_analysis": {
            "voc_summary": "",              # Voice-of-customer summary
            "pain_points": [],
            "dealbreakers": [],
            "usage_scenarios": [],
            "buyer_motivations": [],
            "end_user_avatar": "",
            "buyer_avatar": "",
            "feature_blueprint": [],        # Recommended feature set
            "differentiation_strategy": "",
            "recommendation": "",           # Go / No-go / Conditional
        },

        # ── Tier 3 — Pre-sourcing validation ──────────────────────────────────
        # Triggered when a human moves the idea to "pre_sourcing".
        "presourcing_done": False,
        "presourcing_at": None,
        "presourcing_data": {
            "product_concept": "",
            "buyer_poll_result": "",
            "listing_title": "",
            "bullet_points": [],
            "tagline": "",
            "image_shot_list": [],
            "materials_spec": "",
            "dimensions_assumptions": "",
            "packaging_notes": "",
            "compliance_notes": "",
            "quote_volume_assumptions": "",
            "supplier_search_terms": [],
            "lead_time_assumptions": "",
        },
    }


# ── Valid status values ────────────────────────────────────────────────────────
# Keeping these in a constant means every part of the codebase imports the
# same list rather than spelling strings independently.
VALID_STATUSES = ["new", "scored", "shortlisted", "pre_sourcing", "approved", "dismissed"]

# ── Valid source values ────────────────────────────────────────────────────────
VALID_SOURCES = ["human_seeded", "autonomous", "adjacency_mining"]
