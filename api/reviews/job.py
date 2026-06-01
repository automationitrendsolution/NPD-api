import time
from datetime import datetime, timezone

from django.conf import settings

from api.memory import IdeaMemoryStore
from .scraper import fetch_amazon_reviews
from .parser import parse_amazon_reviews, has_next_page


# Default caps — can be overridden per call
DEFAULT_MAX_ASINS = 3   # Competitor products to scrape
DEFAULT_MAX_PAGES = 3   # Review pages per ASIN  (~10 reviews each)
MIN_REVIEWS_PER_ASIN = 3  # Discard ASINs that returned fewer reviews than this


def _collect_asins(idea):
    """
    Return an ordered, deduplicated list of competitor ASINs from the idea's
    Tier 1 evidence.

    Priority:
      1. competitor_asins list (BA top-clicked + organic SERP, already ranked)
      2. competitor_details list (from detail-page fetches)
      3. SERP results (last resort)
    """
    evidence = idea.get("tier1_evidence", {})
    seen = set()
    asins = []

    def _add(asin):
        if asin and asin not in seen:
            seen.add(asin)
            asins.append(asin)

    for a in evidence.get("competitor_asins", []):
        _add(a)

    for detail in evidence.get("competitor_details", []):
        _add(detail.get("asin"))

    for product in evidence.get("serp_results", [])[:8]:
        _add(product.get("asin"))

    return asins


def run_review_scraping(idea_id, max_asins=DEFAULT_MAX_ASINS,
                        max_pages=DEFAULT_MAX_PAGES, force=False):
    """
    Tier 2A: Scrape Amazon customer reviews for the top competitor products
    of a shortlisted idea and save them to the idea memory store.

    Guard rules
    -----------
    - Idea must exist
    - status must be in (shortlisted, pre_sourcing, approved)
    - reviews_scraped must be False — unless force=True

    Process
    -------
    For each competitor ASIN (up to max_asins):
      - Fetch up to max_pages review pages via ScrapingBee
      - Stop paginating early if the page returns no reviews or has no next page
      - Discard the ASIN if fewer than MIN_REVIEWS_PER_ASIN were collected

    Saves to memory
    ---------------
    review_data.review_pages  → { asin: [list of review dicts] }
    review_data.products_reviewed → [asin, ...]
    reviews_scraped           → True
    reviews_scraped_at        → ISO timestamp

    Returns a result dict with status, counts, and duration.
    """
    t_start = time.time()
    store = IdeaMemoryStore(str(settings.IDEA_MEMORY_PATH))

    idea = store.get(idea_id)
    if idea is None:
        return {
            "status": "error",
            "idea_id": idea_id,
            "error": f"Idea '{idea_id}' not found in memory store.",
        }

    keyword = idea.get("keyword", "?")

    # Status gate — Tier 2A only runs once the human has shortlisted the idea
    eligible_statuses = ("shortlisted", "pre_sourcing", "approved")
    if idea.get("status") not in eligible_statuses:
        return {
            "status": "skipped",
            "idea_id": idea_id,
            "keyword": keyword,
            "skip_reason": (
                f"Idea status is '{idea.get('status')}'. "
                f"Review scraping requires one of: {', '.join(eligible_statuses)}."
            ),
        }

    # Already-done guard
    if idea.get("reviews_scraped") and not force:
        return {
            "status": "skipped",
            "idea_id": idea_id,
            "keyword": keyword,
            "skip_reason": "Reviews already scraped. Pass force=True to re-scrape.",
        }

    # Resolve which ASINs to scrape
    asins = _collect_asins(idea)[:max_asins]
    if not asins:
        return {
            "status": "error",
            "idea_id": idea_id,
            "keyword": keyword,
            "error": (
                "No competitor ASINs found in tier1_evidence. "
                "Run Tier 1 scoring first (python manage.py score_idea)."
            ),
        }

    # ── Scrape ────────────────────────────────────────────────────────────────
    review_pages = {}       # { asin: [review_dict, ...] }
    products_reviewed = []
    total_reviews = 0
    warnings = []

    for asin in asins:
        asin_reviews = []

        for page_num in range(1, max_pages + 1):
            try:
                html = fetch_amazon_reviews(asin, page=page_num)
                page_reviews = parse_amazon_reviews(html)

                if not page_reviews:
                    break  # Empty page — no point fetching more

                asin_reviews.extend(page_reviews)

                if not has_next_page(html):
                    break   # Last page reached

            except Exception as exc:
                warnings.append(f"ASIN {asin} page {page_num}: {exc}")
                break  # Skip remaining pages for this ASIN

        if len(asin_reviews) >= MIN_REVIEWS_PER_ASIN:
            review_pages[asin] = asin_reviews
            products_reviewed.append(asin)
            total_reviews += len(asin_reviews)
        else:
            warnings.append(
                f"ASIN {asin}: only {len(asin_reviews)} review(s) collected "
                f"(minimum {MIN_REVIEWS_PER_ASIN}) — discarded."
            )

    if not review_pages:
        error_detail = "; ".join(warnings) if warnings else "All ASINs returned no reviews."
        return {
            "status": "error",
            "idea_id": idea_id,
            "keyword": keyword,
            "error": f"No usable reviews collected. {error_detail}",
        }

    # ── Save to memory ────────────────────────────────────────────────────────
    store.update(
        idea_id,
        reviews_scraped=True,
        reviews_scraped_at=datetime.now(timezone.utc).isoformat(),
        review_data={
            "products_reviewed": products_reviewed,
            "review_pages":      review_pages,
            # pain_points / use_cases / feature_requests / buyer_objections are
            # populated by the Tier 2C LLM analysis step, not here
            "pain_points":       [],
            "use_cases":         [],
            "feature_requests":  [],
            "buyer_objections":  [],
        },
    )

    duration = round(time.time() - t_start, 1)

    result = {
        "status":          "complete",
        "idea_id":         idea_id,
        "keyword":         keyword,
        "asins_scraped":   products_reviewed,
        "total_reviews":   total_reviews,
        "review_counts":   {asin: len(rv) for asin, rv in review_pages.items()},
        "duration_seconds": duration,
    }

    if warnings:
        result["warnings"] = warnings

    return result
