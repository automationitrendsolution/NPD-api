"""
Tier 1 deterministic sub-score functions.

Each function takes raw evidence and returns a result dict:

    {
        "score":      int,        # 0–100
        "components": dict,       # breakdown showing what drove the score
        "flags":      list[str],  # notable signals (informational, not kill-switches)
    }

All five functions are pure: given the same inputs, they always return
the same output. No API calls, no file I/O, no side effects.

Scoring philosophy
------------------
Higher is always "better" from the pipeline's perspective.

- Demand:          higher = more real search volume and proven purchase intent
- Saturation:      higher = easier entry (fewer dominant incumbents)
- Differentiation: higher = clearer gap to exploit
- Fit:             higher = better category/price/supply-chain fit (0 = hard kill)
- Economic:        higher = better unit economics

The composite in scorer.py applies the weights from config.py.
"""

import re
import statistics
from typing import Optional

from . import config as cfg


# ── Internal helpers ──────────────────────────────────────────────────────────

def _band_lookup(value: float, bands: list, fallback: float) -> float:
    """
    Maps a value to a 0–1 fraction using a descending band table.

    bands is a list of (ceiling, fraction) tuples sorted from lowest ceiling
    to highest.  The first band where value ≤ ceiling wins.

    Example:
        BA_RANK_BANDS = [(500, 1.00), (2000, 0.85), ...]
        _band_lookup(1200, BA_RANK_BANDS, 0.05) → 0.85  (rank 1200 ≤ 2000)
    """
    for ceiling, fraction in bands:
        if value <= ceiling:
            return fraction
    return fallback


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    """Clamps to [lo, hi] and rounds to int."""
    return int(round(max(lo, min(hi, value))))


def _median(values: list) -> Optional[float]:
    if not values:
        return None
    return statistics.median(values)


def _get_organic(serp: list) -> list:
    """Returns only the non-sponsored products from a SERP result list."""
    return [p for p in serp if not p.get("sponsored")]


# ── 1. Demand score ───────────────────────────────────────────────────────────

def score_demand(serp_results: list, ba_row: Optional[dict]) -> dict:
    """
    Measures how much genuine consumer demand exists for this keyword.

    Components
    ----------
    1. Brand Analytics search frequency rank (40 pts if available).
       The most reliable demand signal because it comes from Amazon's own
       search data. A rank of 1 means the single most-searched term on
       Amazon. A rank of 50,000 is a niche term.

    2. SERP organic depth (20 pts).
       How many non-sponsored products appear on page 1?  A dense page
       means many sellers have found this keyword profitable enough to
       optimise for.

    3. Median review count of top organic products (30 pts).
       Reviews accumulate over time from purchases.  High median reviews
       across the category proves sustained purchase volume, not just
       search curiosity.

    4. Sponsored ratio as commercial-intent signal (10 pts).
       Sellers only pay for ads on keywords that convert.  A high ratio
       of sponsored listings indicates advertisers are making money here,
       which implies strong buyer intent.

    If no BA data is available, the BA component is zero and the remaining
    three components are normalised to fill the full 100-point range.
    """
    flags = []
    components = {}

    has_ba = ba_row and ba_row.get("search_frequency_rank")

    # Component 1: BA rank (40 pts if present)
    if has_ba:
        rank = ba_row["search_frequency_rank"]
        ba_fraction = _band_lookup(rank, cfg.BA_RANK_BANDS, cfg.BA_RANK_FALLBACK)
        ba_pts = ba_fraction * 40
        components["ba_frequency_rank"] = {
            "rank": rank, "fraction": ba_fraction, "points": round(ba_pts, 1)
        }
    else:
        ba_pts = 0
        flags.append("no_ba_data")
        components["ba_frequency_rank"] = {"rank": None, "fraction": 0, "points": 0}

    # Component 2: Organic SERP depth (20 pts)
    organic = _get_organic(serp_results)
    organic_count = len(organic)
    # 16 organic results = full page; 10+ = solid; fewer = thin market
    organic_fraction = min(organic_count / 14.0, 1.0)
    organic_pts = organic_fraction * 20
    components["serp_organic_depth"] = {
        "organic_count": organic_count,
        "fraction": round(organic_fraction, 2),
        "points": round(organic_pts, 1),
    }

    # Component 3: Median review count (30 pts)
    review_counts = [
        p["reviews"] for p in serp_results[:12]
        if p.get("reviews") and p["reviews"] > 0
    ]
    med_reviews = _median(review_counts) or 0
    review_fraction = _band_lookup(med_reviews, cfg.REVIEW_COUNT_BANDS, cfg.REVIEW_COUNT_FALLBACK)
    review_pts = review_fraction * 30
    components["median_review_count"] = {
        "median": round(med_reviews),
        "fraction": round(review_fraction, 2),
        "points": round(review_pts, 1),
    }

    # Component 4: Sponsored ratio — commercial intent (10 pts)
    if serp_results:
        sponsored_count = sum(1 for p in serp_results if p.get("sponsored"))
        sponsored_ratio = sponsored_count / len(serp_results)
        # 25–40% sponsored = healthy commercial market
        intent_fraction = min(sponsored_ratio / 0.30, 1.0)
        intent_pts = intent_fraction * 10
    else:
        sponsored_ratio = 0.0
        intent_fraction = 0.0
        intent_pts = 0
    components["sponsored_ratio"] = {
        "ratio": round(sponsored_ratio, 2),
        "fraction": round(intent_fraction, 2),
        "points": round(intent_pts, 1),
    }

    raw_total = ba_pts + organic_pts + review_pts + intent_pts

    # If no BA data, rescale the 60 available points up to 100
    if not has_ba:
        rescale_denominator = organic_pts + review_pts + intent_pts
        if rescale_denominator > 0:
            raw_total = (rescale_denominator / 60.0) * 100.0
        else:
            raw_total = 0.0
        flags.append("score_rescaled_no_ba")

    score = _clamp(raw_total)

    if score >= 75:
        flags.append("strong_demand")
    elif score < 35:
        flags.append("weak_demand")

    return {"score": score, "components": components, "flags": flags}


# ── 2. Saturation score (ease of entry) ──────────────────────────────────────

def score_saturation(serp_results: list, ba_row: Optional[dict]) -> dict:
    """
    Measures how easy it is to enter this market (inverse of competition).

    A HIGH saturation score means the market is EASY to enter.
    A LOW saturation score means it is dominated by entrenched incumbents.

    Components
    ----------
    1. High-review competitor density (35 pts).
       Products with ≥500 reviews are strong incumbents.  If most of page
       1 is full of them, new entrants will struggle for visibility.

    2. Badge concentration (25 pts).
       Best Seller and Amazon's Choice badges give those products a
       significant click advantage.  Many badges = tight competition.

    3. Dominant click share from BA (25 pts).
       If the top-clicked ASIN has >40% click share (from BA data),
       that product has a near-monopoly on buyer attention.

    4. Price band tightness (15 pts).
       A very narrow price range signals a commoditised market where
       differentiation is already minimal.
    """
    flags = []
    components = {}

    # Component 1: High-review competitor density (35 pts)
    top_organic = _get_organic(serp_results)[:10]
    high_review_count = sum(
        1 for p in top_organic
        if (p.get("reviews") or 0) >= cfg.HIGH_REVIEW_THRESHOLD
    )
    # If ≥8 of top 10 organic have >500 reviews → very saturated (ease = low)
    saturation_fraction = high_review_count / max(len(top_organic), 1)
    ease_from_reviews = (1.0 - saturation_fraction) * 35
    components["high_review_density"] = {
        "high_review_count": high_review_count,
        "of_top_organic": len(top_organic),
        "saturation_fraction": round(saturation_fraction, 2),
        "points": round(ease_from_reviews, 1),
    }

    # Component 2: Badge concentration (25 pts)
    badge_count = sum(
        1 for p in serp_results
        if p.get("best_seller") or p.get("amazon_choice")
    )
    # 0 badges = easiest; ≥5 badges = very hard
    badge_ease_fraction = max(0.0, 1.0 - (badge_count / 5.0))
    badge_pts = badge_ease_fraction * 25
    components["badge_concentration"] = {
        "badge_count": badge_count,
        "ease_fraction": round(badge_ease_fraction, 2),
        "points": round(badge_pts, 1),
    }

    # Component 3: Dominant BA click share (25 pts)
    if ba_row and ba_row.get("click_share_1") is not None:
        top_click_share = ba_row["click_share_1"]
        # >50% click share = near-monopoly; 0% = no dominant player
        dominance_ease_fraction = max(0.0, 1.0 - (top_click_share / 0.50))
        dominance_pts = dominance_ease_fraction * 25
        components["ba_click_dominance"] = {
            "top_click_share": round(top_click_share, 3),
            "ease_fraction": round(dominance_ease_fraction, 2),
            "points": round(dominance_pts, 1),
        }
    else:
        # No BA data — assume neutral (moderate dominance)
        dominance_pts = 12.5
        components["ba_click_dominance"] = {
            "top_click_share": None,
            "ease_fraction": 0.5,
            "points": dominance_pts,
        }

    # Component 4: Price band tightness (15 pts)
    prices = [p["price"] for p in top_organic if p.get("price") and p["price"] > 0]
    if len(prices) >= 3:
        med_price = _median(prices)
        price_range = max(prices) - min(prices)
        # Range as a % of median: 100%+ range = lots of room; <15% = commoditised
        range_ratio = price_range / med_price if med_price else 0
        price_ease_fraction = min(range_ratio / 1.0, 1.0)  # cap at 100% range
        price_pts = price_ease_fraction * 15
        components["price_band"] = {
            "min_price": round(min(prices), 2),
            "max_price": round(max(prices), 2),
            "median_price": round(med_price, 2),
            "range_ratio": round(range_ratio, 2),
            "ease_fraction": round(price_ease_fraction, 2),
            "points": round(price_pts, 1),
        }
    else:
        price_pts = 7.5  # neutral
        components["price_band"] = {
            "min_price": None, "max_price": None,
            "median_price": None, "range_ratio": None,
            "ease_fraction": 0.5, "points": price_pts,
        }

    score = _clamp(ease_from_reviews + badge_pts + dominance_pts + price_pts)

    if score >= 70:
        flags.append("low_competition")
    elif score <= 30:
        flags.append("high_saturation")

    return {"score": score, "components": components, "flags": flags}


# ── 3. Differentiation score ──────────────────────────────────────────────────

def score_differentiation(serp_results: list, competitor_details: list) -> dict:
    """
    Measures how much room exists to enter with a meaningfully different product.

    Components
    ----------
    1. Price gap opportunity (35 pts).
       A wide spread between the cheapest and most expensive organic
       products shows the market accepts multiple value tiers.  This means
       a well-positioned product at a premium can capture share above the
       commodity floor without hitting the ceiling.

    2. Rating ceiling gap (30 pts).
       If even the best-reviewed products average 3.5–4.2 stars, customers
       are clearly not fully satisfied.  There is room for a product that
       genuinely solves the complaints.  (≥4.8 average = market is satisfied.)

    3. Brand diversity (20 pts).
       If top-10 organic results are spread across many different brands,
       no single brand has loyalty lock-in.  A new brand can compete on
       product quality alone.  If one brand dominates, brand loyalty is a
       moat that requires a bigger marketing investment to breach.

    4. Feature whitespace signal from bullet points (15 pts).
       If competitor product bullets cluster around the same 3-4 features,
       there is likely an unmet feature need.  We proxy this by measuring
       how unique each product's bullet points are relative to each other.
    """
    flags = []
    components = {}

    organic = _get_organic(serp_results)

    # Component 1: Price gap (35 pts)
    prices = [p["price"] for p in organic if p.get("price") and p["price"] > 0]
    if len(prices) >= 3:
        med_price = _median(prices)
        price_gap_ratio = (max(prices) - min(prices)) / med_price if med_price else 0
        # 100%+ gap = very open; <20% = locked-in
        gap_fraction = min(price_gap_ratio / 1.2, 1.0)
        gap_pts = gap_fraction * 35
        components["price_gap"] = {
            "min": round(min(prices), 2),
            "max": round(max(prices), 2),
            "median": round(med_price, 2),
            "gap_ratio": round(price_gap_ratio, 2),
            "points": round(gap_pts, 1),
        }
    else:
        gap_pts = 17.5  # neutral
        components["price_gap"] = {"min": None, "max": None, "points": gap_pts}

    # Component 2: Rating ceiling gap (30 pts)
    ratings = [p["rating"] for p in organic[:10] if p.get("rating") and p["rating"] > 0]
    if ratings:
        avg_rating = statistics.mean(ratings)
        max_rating = max(ratings)
        # If best product has 4.8+ stars → market is satisfied → low opportunity
        # If avg is 3.5-4.1 → lots of dissatisfied buyers → high opportunity
        ceiling = max_rating
        if ceiling < 3.5:
            rating_pts = 30   # very unhappy market
        elif ceiling < 4.0:
            rating_pts = 25
        elif ceiling < 4.3:
            rating_pts = 20
        elif ceiling < 4.6:
            rating_pts = 12
        else:
            rating_pts = 5    # market is already well-served
        components["rating_gap"] = {
            "avg_rating": round(avg_rating, 2),
            "max_rating": round(ceiling, 2),
            "points": rating_pts,
        }
        if avg_rating < 4.0:
            flags.append("low_avg_rating_opportunity")
    else:
        rating_pts = 15  # neutral
        components["rating_gap"] = {"avg_rating": None, "max_rating": None, "points": rating_pts}

    # Component 3: Brand diversity (20 pts)
    brands = [
        (p.get("brand") or "").strip().lower()
        for p in organic[:10]
        if p.get("brand")
    ]
    if brands:
        unique_brands = len(set(brands))
        total_branded = len(brands)
        diversity_ratio = unique_brands / total_branded
        brand_pts = diversity_ratio * 20
        components["brand_diversity"] = {
            "unique_brands": unique_brands,
            "of_top_organic": total_branded,
            "diversity_ratio": round(diversity_ratio, 2),
            "points": round(brand_pts, 1),
        }
    else:
        brand_pts = 10
        components["brand_diversity"] = {"unique_brands": None, "points": brand_pts}

    # Component 4: Feature whitespace from bullet points (15 pts)
    all_bullets = []
    for product in competitor_details:
        bullets = product.get("bullet_points") or []
        all_bullets.extend([b.lower() for b in bullets if b])

    if len(all_bullets) >= 5:
        unique_words = set()
        for bullet in all_bullets:
            unique_words.update(re.findall(r"\b[a-z]{4,}\b", bullet))
        # More unique words relative to total = more varied feature language = more whitespace
        vocab_richness = min(len(unique_words) / 200.0, 1.0)
        feature_pts = vocab_richness * 15
        components["feature_whitespace"] = {
            "total_bullets": len(all_bullets),
            "unique_keywords": len(unique_words),
            "vocab_richness": round(vocab_richness, 2),
            "points": round(feature_pts, 1),
        }
    else:
        feature_pts = 7.5
        components["feature_whitespace"] = {
            "total_bullets": len(all_bullets), "unique_keywords": None, "points": feature_pts
        }

    score = _clamp(gap_pts + rating_pts + brand_pts + feature_pts)

    if score >= 70:
        flags.append("strong_differentiation_opportunity")
    elif score <= 25:
        flags.append("commoditised_market")

    return {"score": score, "components": components, "flags": flags}


# ── 4. Fit score ──────────────────────────────────────────────────────────────

def score_fit(keyword: str, serp_results: list, competitor_details: list) -> dict:
    """
    Measures how well this idea fits the operational constraints of the business.

    A score of 0 means a hard kill — the idea is definitively unsuitable
    and should be dismissed without further evaluation.

    Components
    ----------
    1. Hard-kill keyword check (instant zero if triggered).
       Matches the keyword against a list of categories the business
       cannot or will not sell (food, books, firearms, etc.).

    2. Hard-kill SERP title check (instant zero if triggered).
       If ≥60% of page-1 titles match a non-sellable product pattern,
       the keyword maps to the wrong market even if the keyword itself looks clean.

    3. Price viability (50 pts).
       Median selling price must be above MIN_VIABLE_PRICE ($15) for FBA
       margins to be achievable.  Below this, fees eat the entire margin.

    4. Price ceiling check (20 pts).
       Extremely high prices (>$80) bring sourcing complexity, longer
       lead times, and higher capital risk.  A slight penalty applies.

    5. FBA-friendly category signal (30 pts).
       A bonus if the keyword contains words that suggest a category with
       a well-understood FBA supply chain (home, kitchen, sports, etc.).
    """
    flags = []
    components = {}
    hard_killed = False
    kill_reason = ""

    # ── Hard kill 1: keyword patterns ─────────────────────────────────────────
    kw_lower = keyword.strip().lower()
    for pattern in cfg.HARD_KILL_KEYWORD_PATTERNS:
        if re.search(pattern, kw_lower):
            hard_killed = True
            kill_reason = f"keyword matches hard-kill pattern: {pattern}"
            break

    if hard_killed:
        return {
            "score": 0,
            "hard_killed": True,
            "kill_reason": kill_reason,
            "components": {},
            "flags": ["hard_kill"],
        }

    # ── Hard kill 2: SERP title patterns ──────────────────────────────────────
    top_titles = [
        (p.get("title") or "").lower()
        for p in serp_results[:10]
    ]
    if top_titles:
        kill_title_hits = 0
        for title in top_titles:
            for pattern in cfg.HARD_KILL_TITLE_PATTERNS:
                if re.search(pattern, title):
                    kill_title_hits += 1
                    break
        kill_title_ratio = kill_title_hits / len(top_titles)
        if kill_title_ratio >= 0.60:
            return {
                "score": 0,
                "hard_killed": True,
                "kill_reason": (
                    f"{kill_title_hits}/{len(top_titles)} SERP titles match "
                    f"hard-kill title patterns"
                ),
                "components": {},
                "flags": ["hard_kill", "wrong_product_type"],
            }

    # ── Component 1: Price viability (50 pts) ─────────────────────────────────
    organic = _get_organic(serp_results)
    prices = [p["price"] for p in organic if p.get("price") and p["price"] > 0]
    med_price = _median(prices) if prices else None

    if med_price is None:
        # No price data — can't confirm viability
        price_pts = 25
        flags.append("no_price_data")
    elif med_price < cfg.MIN_VIABLE_PRICE:
        price_pts = 0
        flags.append("price_too_low")
        hard_killed = True
        kill_reason = (
            f"Median price ${med_price:.2f} is below minimum viable "
            f"price ${cfg.MIN_VIABLE_PRICE:.2f}"
        )
    elif med_price < cfg.MIN_VIABLE_PRICE * 1.3:
        price_pts = 20  # marginal
        flags.append("price_marginal")
    else:
        price_pts = 50

    components["price_viability"] = {
        "median_price": round(med_price, 2) if med_price else None,
        "min_viable": cfg.MIN_VIABLE_PRICE,
        "points": price_pts,
    }

    if hard_killed:
        return {
            "score": 0,
            "hard_killed": True,
            "kill_reason": kill_reason,
            "components": components,
            "flags": flags + ["hard_kill"],
        }

    # ── Component 2: Price ceiling check (20 pts) ──────────────────────────────
    if med_price and med_price > cfg.MAX_PRACTICAL_PRICE:
        ceiling_pts = 10  # slight penalty, not a kill
        flags.append("price_complex_sourcing")
    else:
        ceiling_pts = 20
    components["price_ceiling"] = {
        "median_price": round(med_price, 2) if med_price else None,
        "max_practical": cfg.MAX_PRACTICAL_PRICE,
        "points": ceiling_pts,
    }

    # ── Component 3: FBA-friendly category signal (30 pts) ────────────────────
    category_hits = sum(
        1 for signal in cfg.FBA_FRIENDLY_CATEGORY_SIGNALS
        if signal in kw_lower
    )
    if category_hits >= 2:
        category_pts = 30
        flags.append("strong_category_fit")
    elif category_hits == 1:
        category_pts = 20
    else:
        category_pts = 10  # not a kill, just lower confidence
    components["category_fit"] = {
        "keyword_signals_matched": category_hits,
        "points": category_pts,
    }

    score = _clamp(price_pts + ceiling_pts + category_pts)

    return {
        "score": score,
        "hard_killed": False,
        "kill_reason": "",
        "components": components,
        "flags": flags,
    }


# ── 5. Economic viability score ───────────────────────────────────────────────

def score_economic(serp_results: list, competitor_details: list) -> dict:
    """
    Measures whether the unit economics are viable for an Amazon FBA business.

    Components
    ----------
    1. Profit per unit after fees (60 pts).
       The most critical check.  Assumes:
         - Selling price = median organic SERP price
         - Amazon referral fee = 15 % of price
         - FBA fulfillment fee = $4.50 average per unit
         - COGS = 33 % of selling price (standard FBA target)
       Net profit = price - referral - fulfillment - COGS

    2. Monthly revenue opportunity (40 pts).
       Estimates total category revenue using the top competitors' review
       counts as a proxy for their sales velocity.

       Formula (industry heuristic):
         estimated_monthly_units ≈ review_count × 0.05
         monthly_revenue ≈ sum(monthly_units × price) for top-5 products

       This is conservative.  The real number is likely higher, but we
       bias toward caution at this stage.

    Returns
    -------
    dict with:
        score         : 0–100
        components    : breakdown
        price_band_low: min organic price seen
        price_band_high: max organic price seen
        flags         : list of flag strings
    """
    flags = []
    components = {}

    organic = _get_organic(serp_results)
    prices = [p["price"] for p in organic if p.get("price") and p["price"] > 0]
    med_price = _median(prices) if prices else None

    price_band_low  = round(min(prices), 2) if prices else None
    price_band_high = round(max(prices), 2) if prices else None

    # ── Component 1: Profit per unit (60 pts) ──────────────────────────────────
    if med_price is None:
        profit_pts = 30  # neutral — no price data
        profit_per_unit = None
        flags.append("no_price_data")
        components["profit_per_unit"] = {
            "selling_price": None,
            "referral_fee": None,
            "fulfillment_fee": None,
            "cogs": None,
            "net_profit": None,
            "points": profit_pts,
        }
    else:
        referral_fee    = med_price * cfg.AMAZON_REFERRAL_FEE_RATE
        fulfillment_fee = cfg.FBA_FULFILLMENT_FEE_AVG
        cogs            = med_price * cfg.COGS_TARGET_RATIO
        profit_per_unit = med_price - referral_fee - fulfillment_fee - cogs

        if profit_per_unit < cfg.MIN_PROFIT_PER_UNIT:
            profit_pts = 0
            flags.append("below_min_profit")
        elif profit_per_unit < cfg.MIN_PROFIT_PER_UNIT * 1.5:
            profit_pts = 20  # marginal
            flags.append("marginal_profit")
        elif profit_per_unit < cfg.MIN_PROFIT_PER_UNIT * 2.5:
            profit_pts = 40
        elif profit_per_unit < cfg.MIN_PROFIT_PER_UNIT * 4.0:
            profit_pts = 55
        else:
            profit_pts = 60

        components["profit_per_unit"] = {
            "selling_price":  round(med_price, 2),
            "referral_fee":   round(referral_fee, 2),
            "fulfillment_fee": fulfillment_fee,
            "cogs":           round(cogs, 2),
            "net_profit":     round(profit_per_unit, 2),
            "points":         profit_pts,
        }

    # ── Component 2: Monthly revenue opportunity (40 pts) ─────────────────────
    # Gather review counts from SERP and product detail pages
    review_counts_serp = [
        p["reviews"] for p in serp_results[:5]
        if (p.get("reviews") or 0) > 0
    ]
    review_counts_detail = [
        p["review_count"] for p in competitor_details
        if (p.get("review_count") or 0) > 0
    ]
    # Merge, prefer detail page counts (more accurate) over SERP estimates
    all_review_counts = review_counts_detail or review_counts_serp

    if all_review_counts and med_price:
        estimated_monthly_units = sum(rc * 0.05 for rc in all_review_counts[:5])
        estimated_monthly_revenue = estimated_monthly_units * med_price

        if estimated_monthly_revenue < cfg.MIN_MONTHLY_REVENUE:
            revenue_pts = 0
            flags.append("low_revenue_opportunity")
        elif estimated_monthly_revenue < cfg.MIN_MONTHLY_REVENUE * 3:
            revenue_pts = 15
        elif estimated_monthly_revenue < cfg.MIN_MONTHLY_REVENUE * 8:
            revenue_pts = 28
        else:
            revenue_pts = 40

        components["monthly_revenue"] = {
            "estimated_monthly_units": round(estimated_monthly_units),
            "estimated_monthly_revenue": round(estimated_monthly_revenue, 2),
            "min_threshold": cfg.MIN_MONTHLY_REVENUE,
            "points": revenue_pts,
        }
    else:
        revenue_pts = 20  # neutral
        components["monthly_revenue"] = {
            "estimated_monthly_units": None,
            "estimated_monthly_revenue": None,
            "min_threshold": cfg.MIN_MONTHLY_REVENUE,
            "points": revenue_pts,
        }

    score = _clamp(profit_pts + revenue_pts)

    if score >= 70:
        flags.append("strong_economics")
    elif score <= 20:
        flags.append("poor_economics")

    return {
        "score": score,
        "components": components,
        "price_band_low":  price_band_low,
        "price_band_high": price_band_high,
        "flags": flags,
    }


# ── Composite score ───────────────────────────────────────────────────────────

def compute_composite(sub_scores: dict) -> int:
    """
    Combines the five sub-scores into one overall Tier 1 score (0–100).

    If fit.score == 0 (hard kill), the composite is forced to 0 regardless
    of how good the other scores are — there is no point pursuing an idea
    we cannot physically sell.

    Parameters
    ----------
    sub_scores : dict
        Keys: demand, saturation, differentiation, fit, economic_viability.
        Each value must be an int 0–100.

    Returns
    -------
    int
        Weighted composite score 0–100.
    """
    if sub_scores.get("fit", 0) == 0:
        return 0

    total = sum(
        cfg.SCORE_WEIGHTS[key] * sub_scores[key]
        for key in cfg.SCORE_WEIGHTS
        if key in sub_scores
    )

    return _clamp(total)
