"""
Tier 1 scoring configuration.

All tuneable numbers are here. The scoring logic in sub_scores.py and
scorer.py imports from this file and never hard-codes values, so you
can adjust thresholds and weights without touching the formulas.
"""

# ── Composite score weights ────────────────────────────────────────────────────
# Must sum to 1.0.
# Demand is weighted most heavily because without genuine search volume,
# no amount of low competition or good economics can save an idea.
SCORE_WEIGHTS = {
    "demand":             0.35,
    "saturation":         0.25,   # scored as ease-of-entry; higher = easier
    "differentiation":    0.20,
    "fit":                0.10,
    "economic_viability": 0.10,
}

# ── Score thresholds ───────────────────────────────────────────────────────────
TIER1_MINIMUM_SCORE   = 45   # Below → dismissed + cooldown applied
TIER1_TASK_THRESHOLD  = 55   # Above → task board entry created
TIER1_5_THRESHOLD     = 70   # Above → eligible for Tier 1.5 external enrichment

# ── Cooldown durations (hours) ─────────────────────────────────────────────────
COOLDOWN_HOURS_LOW_SCORE  = 168   # 7 days for below-minimum ideas
COOLDOWN_HOURS_DISMISSED  = 720   # 30 days for hard-killed ideas

# ── Scrape depth ───────────────────────────────────────────────────────────────
SERP_PAGES = 1                   # How many SERP pages to fetch per keyword
MAX_COMPETITOR_DETAILS = 4       # Product detail pages to fetch per idea

# ── Brand Analytics rank → demand signal mapping ──────────────────────────────
# Each tuple is (rank_ceiling, score_fraction).
# A keyword ranked ≤500 gets the full 1.0 signal; one ranked >100000 gets 0.05.
# Tiers are evaluated top-to-bottom; the first match wins.
BA_RANK_BANDS = [
    (500,    1.00),
    (2000,   0.85),
    (5000,   0.70),
    (10000,  0.55),
    (25000,  0.38),
    (50000,  0.22),
    (100000, 0.10),
]
BA_RANK_FALLBACK = 0.05          # When rank > 100000

# ── Review count → demand signal mapping ──────────────────────────────────────
# Median review count of the top 10 SERP products.
REVIEW_COUNT_BANDS = [
    (3000,  1.00),
    (1500,  0.88),
    (800,   0.74),
    (400,   0.58),
    (150,   0.40),
    (50,    0.22),
    (10,    0.10),
]
REVIEW_COUNT_FALLBACK = 0.04

# ── High-review competitor threshold ──────────────────────────────────────────
# Products with ≥ this many reviews are considered "strong" incumbents.
HIGH_REVIEW_THRESHOLD = 500

# ── Economics — US FBA ─────────────────────────────────────────────────────────
AMAZON_REFERRAL_FEE_RATE  = 0.15   # 15 % of selling price
FBA_FULFILLMENT_FEE_AVG   = 4.50   # Average FBA fee per unit in USD
COGS_TARGET_RATIO         = 0.33   # COGS should be ≤ 33 % of selling price
MIN_PROFIT_PER_UNIT       = 5.00   # Below this → economic hard fail
MIN_VIABLE_PRICE          = 15.00  # Below this → margins are near-impossible
MAX_PRACTICAL_PRICE       = 80.00  # Above this → sourcing complexity rises sharply

# Minimum estimated monthly category revenue to be worth entering
MIN_MONTHLY_REVENUE = 3_000.0

# ── Hard-kill keyword patterns ─────────────────────────────────────────────────
# Matched against the idea keyword (lowercased).  A match skips all scraping
# and marks the idea dismissed immediately.
HARD_KILL_KEYWORD_PATTERNS = [
    # Digital / media products — unsourceable physical goods
    r"\bbook\b", r"\bbooks\b", r"\bnovel\b", r"\bkindle\b", r"\beboo?k\b",
    r"\bmusic\b", r"\bvinyl\b", r"\balbum\b", r"\bcd\b",
    r"\bdvd\b", r"\bblu.?ray\b", r"\bvideo\s+game\b", r"\bvideogame\b",
    r"\bsoftware\b", r"\bdigital\s+download\b", r"\bgift\s+card\b",
    # Consumables / food & beverage — different supply chain
    r"\bfood\b", r"\bsnack\b", r"\bdrink\b", r"\bbeverage\b",
    r"\bcoffee\b", r"\btea\b", r"\bprotein\s+powder\b",
    r"\bsupplement\b", r"\bvitamin\b", r"\bprobio\w+\b",
    # Medical / pharmaceutical — regulated
    r"\bprescription\b", r"\bpharmaceutical\b",
    r"\bmedical\s+device\b", r"\bfda\s+approv\w+\b",
    # Dangerous / restricted
    r"\btobacco\b", r"\bcigarette\b", r"\bvape\b", r"\be.?cig\b",
    r"\balcohol\b", r"\bwine\b", r"\bbeer\b", r"\bspirits\b", r"\bliquor\b",
    r"\bfirearm\b", r"\bgun\b", r"\bammo\b", r"\bbullet\b", r"\bweapon\b",
    r"\bexplosive\b", r"\bhazmat\b",
    # Livestock / live plants — logistics non-starter
    r"\blive\s+animal\b", r"\blive\s+plant\b", r"\blive\s+fish\b",
]

# ── Hard-kill SERP title patterns ──────────────────────────────────────────────
# If ≥ 60 % of top-10 SERP titles match any of these, the idea is killed.
# Catches cases where the keyword is fine but the market is full of
# the wrong product type.
HARD_KILL_TITLE_PATTERNS = [
    r"\brecipe\b", r"\bcookbook\b",
    r"\bpaper\s+back\b", r"\bhard\s*cover\b",
    r"\bmagazine\b", r"\bnewspaper\b",
]

# ── Known FBA-friendly category signals ───────────────────────────────────────
# Keywords that suggest the idea sits in a well-sourced, FBA-friendly category.
# These are used to add a small fit bonus (not required — absence is not a kill).
FBA_FRIENDLY_CATEGORY_SIGNALS = [
    "kitchen", "home", "garden", "outdoor", "sports", "fitness", "yoga",
    "travel", "office", "desk", "storage", "organizer", "baby", "kids",
    "pet", "dog", "cat", "craft", "art", "tools", "hardware", "cleaning",
    "bath", "beauty", "skincare", "hair", "phone", "case", "laptop", "bag",
    "backpack", "wallet", "purse", "shoes", "apparel", "clothing",
]
