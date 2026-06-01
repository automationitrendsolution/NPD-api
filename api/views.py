import json

from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .memory import IdeaMemoryStore, VALID_STATUSES
from .brand_analytics import db as ba_db
from .brand_analytics.db import get_db_stats, get_latest_ingestion
from .scoring.scorer import score_idea
from .scoring import config as scoring_config
from .llm.tier2c import run_tier2c
from .llm.tier3 import run_tier3
from .reviews.job import run_review_scraping
from .search.scraper import fetch_amazon_search
from .search.parser import parse_amazon_results
from .product.scraper import fetch_amazon_product
from .product.parser import parse_amazon_product


# One shared store instance for all memory views.
_store = IdeaMemoryStore(str(settings.IDEA_MEMORY_PATH))


@api_view(["GET"])
def amazon_search(request):
    
    keyword = request.GET.get("keyword", "").strip()
    page = request.GET.get("page", "1")

    if not keyword:
        return Response(
            {"error": "keyword required"},
            status=400
        )

    try:
        page = int(page)
    except ValueError:
        return Response(
            {"error": "page must be an integer"},
            status=400
        )

    try:
        html = fetch_amazon_search(keyword, page=page)

        products = parse_amazon_results(html)

        return Response({
            "keyword": keyword,
            "page": page,
            "product_count": len(products),
            "products": products
        })

    except Exception as e:
        return Response(
            {"error": str(e)},
            status=500
        )


@api_view(["GET"])
def amazon_product_detail(request):

    asin = request.GET.get("asin", "").strip()
    product_url = request.GET.get("url", "").strip()

    if not asin and not product_url:
        return Response(
            {"error": "asin or url required"},
            status=400
        )

    try:
        html = fetch_amazon_product(product_url=product_url or None, asin=asin or None)
        product = parse_amazon_product(html)

        return Response({
            "asin": asin or product.get("asin"),
            "product_url": product_url,
            "product": product,
        })

    except Exception as e:
        return Response(
            {"error": str(e)},
            status=500
        )


# ── Idea Memory endpoints ─────────────────────────────────────────────────────


@api_view(["POST"])
def idea_create(request):
    """
    Create a new idea record in the memory store.

    POST /api/ideas/
    Body (JSON):
        {
            "keyword": "bamboo travel mug",         <- required
            "concept": "eco-friendly commuter mug", <- optional
            "source": "human_seeded"                <- optional, default human_seeded
        }

    Returns the full idea record on success (HTTP 201).
    Returns HTTP 400 if the keyword is missing or already exists.
    """
    body = request.data

    keyword = body.get("keyword", "").strip()
    if not keyword:
        return Response({"error": "keyword is required"}, status=400)

    concept = body.get("concept", "").strip()
    source = body.get("source", "human_seeded").strip()

    try:
        idea = _store.create(keyword=keyword, concept=concept, source=source)
        return Response(idea, status=201)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)


@api_view(["GET"])
def idea_list(request):
    """
    List ideas from the memory store, with optional filters.

    GET /api/ideas/
    Query params (all optional):
        status            -> e.g. scored, shortlisted
        source            -> e.g. human_seeded, autonomous
        tier1_done        -> true | false
        reviews_scraped   -> true | false
        research_done     -> true | false
        presourcing_done  -> true | false
        has_flag          -> e.g. hard_kill
        min_tier1_score   -> e.g. 60

    Returns { "count": N, "ideas": [...] }
    """

    def _bool(val):
        if val is None:
            return None
        return val.lower() in ("true", "1", "yes")

    def _float(val):
        if val is None:
            return None
        try:
            return float(val)
        except ValueError:
            return None

    filters = {
        "status":           request.GET.get("status"),
        "source":           request.GET.get("source"),
        "tier1_done":       _bool(request.GET.get("tier1_done")),
        "reviews_scraped":  _bool(request.GET.get("reviews_scraped")),
        "research_done":    _bool(request.GET.get("research_done")),
        "presourcing_done": _bool(request.GET.get("presourcing_done")),
        "has_flag":         request.GET.get("has_flag"),
        "min_tier1_score":  _float(request.GET.get("min_tier1_score")),
    }
    # Drop None values so filter() uses its own defaults
    filters = {k: v for k, v in filters.items() if v is not None}

    ideas = _store.filter(**filters)
    return Response({"count": len(ideas), "ideas": ideas})


@api_view(["GET"])
def idea_detail(request, idea_id):
    """
    Retrieve a single idea by its idea_id.

    GET /api/ideas/<idea_id>/

    Returns the full idea record or HTTP 404.
    """
    idea = _store.get(idea_id)
    if idea is None:
        return Response({"error": f"Idea '{idea_id}' not found"}, status=404)
    return Response(idea)


@api_view(["PATCH"])
def idea_update(request, idea_id):
    """
    Update fields on an existing idea.

    PATCH /api/ideas/<idea_id>/update/
    Body (JSON): any subset of top-level idea fields, e.g.
        { "status": "scored", "tier1_score": 74, "tier1_done": true }
        { "flags": ["low_demand"] }
        { "tier1_scores": { "demand": 60, "saturation": 55 } }

    For dict fields (tier1_scores, tier1_evidence, etc.) the patch is
    merged into the existing dict so you do not need to resend unchanged
    sub-keys.

    Returns the full updated idea record or HTTP 404 / 400.
    """
    if not request.data:
        return Response({"error": "Request body must not be empty"}, status=400)

    # Protect identity fields from being overwritten via the API.
    immutable = {"idea_id", "created_at", "keyword"}
    disallowed = immutable & set(request.data.keys())
    if disallowed:
        return Response(
            {"error": f"Fields {sorted(disallowed)} cannot be updated via this endpoint"},
            status=400,
        )

    try:
        updated = _store.update(idea_id, **request.data)
        return Response(updated)
    except KeyError as e:
        return Response({"error": str(e)}, status=404)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)


# ── Brand Analytics endpoints ─────────────────────────────────────────────────


@api_view(["GET"])
def ba_lookup(request):
    """
    Look up a single keyword in the Brand Analytics index.

    GET /api/brand-analytics/lookup/?keyword=bamboo+travel+mug

    Optional query params:
        report_date  → restrict to a specific period, e.g. "2026-05"

    Returns the matching BA row or a "not_found" flag.

    The Tier 1 scorer calls this for every idea keyword before scoring.
    The response tells it: how popular is this keyword, which ASINs are
    the actual market leaders, and what share of clicks they hold.
    """
    keyword = request.GET.get("keyword", "").strip()
    if not keyword:
        return Response({"error": "keyword query parameter is required"}, status=400)

    report_date = request.GET.get("report_date", None)
    db_path = str(settings.BA_DB_PATH)

    try:
        row = ba_db.lookup(db_path, keyword, report_date=report_date)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

    if row is None:
        return Response({
            "keyword": keyword.lower(),
            "found": False,
            "data": None,
        })

    return Response({
        "keyword": keyword.lower(),
        "found": True,
        "data": row,
    })


@api_view(["GET"])
def ba_lookup_batch(request):
    """
    Look up multiple keywords in one request.

    GET /api/brand-analytics/lookup-batch/?keywords=bamboo+mug,silicone+bib,travel+cup

    Optional query params:
        report_date  → restrict to a specific period

    Returns a dict keyed by keyword, each value is the BA row or null.

    Use this when you want to validate a list of keyword variants for one
    idea before deciding which to run through the full scorer.
    """
    raw = request.GET.get("keywords", "").strip()
    if not raw:
        return Response({"error": "keywords query parameter is required"}, status=400)

    keywords = [k.strip() for k in raw.split(",") if k.strip()]
    if len(keywords) > 50:
        return Response(
            {"error": "Maximum 50 keywords per batch request"},
            status=400,
        )

    report_date = request.GET.get("report_date", None)
    db_path = str(settings.BA_DB_PATH)

    try:
        results = ba_db.lookup_batch(db_path, keywords, report_date=report_date)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

    found_count = sum(1 for v in results.values() if v is not None)
    return Response({
        "queried": len(keywords),
        "found": found_count,
        "results": results,
    })


@api_view(["GET"])
def ba_status(request):
    """
    Returns the current state of the Brand Analytics database.

    GET /api/brand-analytics/status/

    Returns:
        total_terms      → number of search terms indexed
        report_dates     → list of periods available (e.g. ["2026-05", "2026-04"])
        last_ingestion   → details of the most recent successful ingestion run
        db_path          → path to the SQLite file (for debugging)

    Use this to confirm the database has been populated before running Tier 1.
    """
    db_path = str(settings.BA_DB_PATH)

    try:
        stats = get_db_stats(db_path)
        last = get_latest_ingestion(db_path)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

    return Response({
        "db_path": db_path,
        "total_terms": stats["total_terms"],
        "report_dates": stats["report_dates"],
        "last_ingestion": dict(last) if last else None,
    })


# ── Tier 1 scoring endpoint ───────────────────────────────────────────────────


@api_view(["POST"])
def score_idea_view(request):
    """
    Run the full Tier 1 scoring pipeline for one product idea keyword.

    POST /api/score/
    Body (JSON):
        {
            "keyword":      "bamboo travel mug",   <- required (or idea_id)
            "idea_id":      "uuid-...",             <- optional, use existing idea
            "concept":      "eco-friendly mug",    <- optional
            "source":       "human_seeded",        <- optional, default human_seeded
            "force_rescore": false                 <- optional, re-score even if done
        }

    What this does
    --------------
    1. Creates or retrieves the idea record in the memory store
    2. Checks cooldown and existing score (skips unless force_rescore=true)
    3. Applies hard-kill keyword rules (instant 0, no scraping)
    4. Fetches the Amazon SERP for the keyword (costs 1 scraping credit)
    5. Looks up the keyword in the Brand Analytics SQLite index
    6. Fetches product detail pages for top competitor ASINs (1 credit each)
    7. Runs all 5 deterministic sub-scorers
    8. Computes the weighted composite score
    9. Saves all evidence + scores to the memory store
   10. Applies a cooldown if the score is below the minimum threshold

    Returns
    -------
    {
        "status":          "scored" | "dismissed" | "skipped" | "error",
        "idea_id":         "uuid-...",
        "keyword":         "bamboo travel mug",
        "tier1_score":     74,
        "tier1_scores": {
            "demand": 80, "saturation": 65, "differentiation": 70,
            "fit": 100, "economic_viability": 60
        },
        "score_breakdown": { ... per-component detail ... },
        "flags":           ["no_ba_data", "strong_demand"],
        "eligible_for_tier15": true,
        "duration_seconds": 12.4
    }

    Scoring thresholds (from config)
    ---------------------------------
        < 45  → dismissed
        45-54 → scored but below task-creation threshold
        55-69 → scored, task created on the board
        70+   → eligible for Tier 1.5 external enrichment
    """
    keyword  = (request.data.get("keyword") or "").strip()
    idea_id  = (request.data.get("idea_id") or "").strip() or None
    concept  = (request.data.get("concept") or "").strip()
    source   = (request.data.get("source") or "human_seeded").strip()
    force    = bool(request.data.get("force_rescore", False))

    if not keyword and not idea_id:
        return Response(
            {"error": "Provide 'keyword' or 'idea_id' in the request body"},
            status=400,
        )

    result = score_idea(
        keyword=keyword,
        idea_id=idea_id,
        concept=concept,
        source=source,
        force_rescore=force,
    )

    # Return 200 for all statuses except error (error is still 200 so the
    # caller can read the error message; use status field to branch logic)
    return Response(result)


# ── LLM endpoints ─────────────────────────────────────────────────────────────


@api_view(["POST"])
def analyse_idea(request):
    """
    Run Tier 2C Enhanced NPD Analysis using OpenAI GPT-4o.

    POST /api/analyse/
    Body (JSON):
        {
            "idea_id":      "uuid-...",     <- required
            "force":        false           <- optional, re-run if already done
        }

    Prerequisites
    -------------
    - idea must exist in the memory store
    - tier1_done must be True (Tier 1 scoring must have run first)
    - reviews_scraped and research_done are optional but improve quality

    What GPT-4o does
    ----------------
    Reads ALL evidence collected so far (SERP data, competitor details,
    Brand Analytics, reviews, research report) and synthesises it into:

        voc_summary             Voice-of-customer in 3-5 sentences
        pain_points             Specific recurring complaints from reviews
        dealbreakers            Reasons buyers return or leave bad reviews
        usage_scenarios         How buyers actually use this product
        buyer_motivations       Why buyers choose this category
        end_user_avatar         Profile of who uses the product
        buyer_avatar            Profile of who makes the purchase decision
        feature_blueprint       Feature recommendations mapped to pain points
        differentiation_strategy  How to compete and win
        recommendation          Go / No-go / Conditional + reasoning

    The LLM never invents market data — it only synthesises provided evidence.

    Returns
    -------
    {
        "status":         "complete" | "skipped" | "error",
        "idea_id":        "...",
        "keyword":        "...",
        "recommendation": "Go",
        "analysis":       { ... full structured output ... },
        "duration_seconds": 12.4
    }
    """
    idea_id = (request.data.get("idea_id") or "").strip()
    force   = bool(request.data.get("force", False))

    if not idea_id:
        return Response({"error": "'idea_id' is required"}, status=400)

    result = run_tier2c(idea_id, force=force)
    return Response(result)


@api_view(["POST"])
def presource_idea(request):
    """
    Run Tier 3 Pre-Sourcing Generation using OpenAI GPT-4o-mini.

    POST /api/presource/
    Body (JSON):
        {
            "idea_id": "uuid-...",   <- required
            "force":   false         <- optional
        }

    Makes three sequential LLM calls:

    Call 1 — Product Concept + Buyer Poll
        Defines the product precisely and tests it against the leading
        competitor in a simulated buyer preference test.

    Call 2 — Amazon Listing Draft
        Title (keyword-first, 200 chars), 5 benefit-led bullet points,
        tagline, and a shot-by-shot image brief.

    Call 3 — Manufacturer Sourcing Spec
        Materials, dimensions, packaging, compliance requirements,
        MOQ/quote volumes, Alibaba search terms, lead-time estimates.

    Returns
    -------
    {
        "status": "complete" | "skipped" | "error",
        "idea_id": "...",
        "keyword": "...",
        "presourcing_data": {
            "product_concept":          "...",
            "buyer_poll_result":        "our_product — ...",
            "listing_title":            "...",
            "bullet_points":            ["...", "..."],
            "tagline":                  "...",
            "image_shot_list":          [...],
            "materials_spec":           "...",
            "dimensions_assumptions":   "...",
            "packaging_notes":          "...",
            "compliance_notes":         "...",
            "quote_volume_assumptions": "...",
            "supplier_search_terms":    ["..."],
            "lead_time_assumptions":    "..."
        },
        "duration_seconds": 28.1
    }
    """
    idea_id = (request.data.get("idea_id") or "").strip()
    force   = bool(request.data.get("force", False))

    if not idea_id:
        return Response({"error": "'idea_id' is required"}, status=400)

    result = run_tier3(idea_id, force=force)
    return Response(result)


# ── Tier 2A review scraping endpoint ─────────────────────────────────────────


@api_view(["POST"])
def scrape_reviews_view(request):
    """
    Run Tier 2A: scrape Amazon customer reviews for a shortlisted idea.

    POST /api/reviews/scrape/
    Body (JSON):
        {
            "idea_id":   "uuid-...",   <- required
            "max_pages": 3,            <- optional, review pages per ASIN (default 3)
            "max_asins": 3,            <- optional, competitor ASINs to scrape (default 3)
            "force":     false         <- optional, re-scrape if already done
        }

    Prerequisites
    -------------
    - Idea must exist in the memory store
    - status must be "shortlisted" (human must shortlist the idea first)
    - Tier 1 scoring must have run so competitor ASINs are in tier1_evidence

    What this does
    --------------
    Fetches up to (max_asins × max_pages) review pages from Amazon using
    ScrapingBee. Each page yields ~10 reviews. Reviews are saved verbatim to
    idea["review_data"]["review_pages"][asin] as a list of dicts:
        { review_id, title, rating, date, text, verified_purchase, helpful_votes }

    Tier 2C (GPT-4o synthesis) reads this corpus to generate pain points,
    dealbreakers, VOC summary, and the feature blueprint.

    Returns
    -------
    {
        "status":          "complete" | "skipped" | "error",
        "idea_id":         "...",
        "keyword":         "...",
        "asins_scraped":   ["B0...", "B0..."],
        "total_reviews":   54,
        "review_counts":   { "B0...": 30, "B0...": 24 },
        "duration_seconds": 38.2,
        "warnings":        []    <- partial failures, if any
    }
    """
    idea_id   = (request.data.get("idea_id") or "").strip()
    max_pages = int(request.data.get("max_pages", 3))
    max_asins = int(request.data.get("max_asins", 3))
    force     = bool(request.data.get("force", False))

    if not idea_id:
        return Response({"error": "'idea_id' is required"}, status=400)

    if max_pages < 1 or max_pages > 10:
        return Response({"error": "'max_pages' must be between 1 and 10"}, status=400)

    if max_asins < 1 or max_asins > 5:
        return Response({"error": "'max_asins' must be between 1 and 5"}, status=400)

    result = run_review_scraping(
        idea_id,
        max_pages=max_pages,
        max_asins=max_asins,
        force=force,
    )
    return Response(result)