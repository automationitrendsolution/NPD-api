# NPD API — Complete Documentation

**New Product Discovery pipeline API built with Django 6 + Django REST Framework.**

Automates the discovery, validation, and pre-sourcing of Amazon FBA product ideas from raw keyword signals all the way through to a manufacturer-ready sourcing specification.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture & Pipeline Flow](#2-architecture--pipeline-flow)
3. [Setup & Installation](#3-setup--installation)
4. [Environment Variables](#4-environment-variables)
5. [API Endpoints](#5-api-endpoints)
   - [Amazon Scraping](#51-amazon-scraping)
   - [Idea Memory](#52-idea-memory)
   - [Brand Analytics](#53-brand-analytics)
   - [Tier 1 Scoring](#54-tier-1-scoring)
   - [Tier 2A — Review Scraping](#55-tier-2a--review-scraping)
   - [Tier 2C — LLM Analysis](#56-tier-2c--llm-analysis)
   - [Tier 3 — Pre-Sourcing](#57-tier-3--pre-sourcing)
6. [CLI Management Commands](#6-cli-management-commands)
7. [Idea Record Schema](#7-idea-record-schema)
8. [Scoring System](#8-scoring-system)
9. [Configuration Reference](#9-configuration-reference)
10. [Project Structure](#10-project-structure)

---

## 1. Project Overview

The NPD system is a product discovery and validation pipeline. It takes a product keyword, validates demand and competition across multiple data sources, enriches strong candidates with customer review data and LLM analysis, then packages the best ideas into a manufacturer-ready document set.

**What it does NOT do:**
- It does not launch or source products
- The LLM never invents market data — it only synthesises evidence collected from real sources
- Human approval is required at two gates before expensive work runs

**Tech stack:**
- Django 6.0.5
- Django REST Framework 3.17.1
- OpenAI API (`gpt-4o` + `gpt-4o-mini`)
- ScrapingBee API (Amazon SERP, product detail, reviews)
- Amazon SP-API (Brand Analytics reports)
- SQLite (Brand Analytics keyword index)
- NDJSON file (idea memory store)

---

## 2. Architecture & Pipeline Flow

```
Keyword input
    ↓
Tier 1: Market scan + deterministic scoring          [automated]
    ↓  (score ≥ 55)
Human shortlists idea on task board                  [human gate]
    ↓
Tier 2A: Amazon review scraping                      [automated]
    ↓
Tier 2C: GPT-4o customer insight analysis            [automated]
    ↓
Human moves idea to pre-sourcing                     [human gate]
    ↓
Tier 3: GPT-4o-mini pre-sourcing doc generation      [automated]
    ↓
Human approves or dismisses                          [human decision]
    ↓
Sourcing begins outside NPD
```

### Scoring thresholds

| Score | Outcome |
|---|---|
| < 45 | Dismissed + 7-day cooldown |
| 45–54 | Scored, no task board entry |
| 55–69 | Scored + task board entry created |
| 70+ | Eligible for Tier 1.5 external enrichment |

---

## 3. Setup & Installation

### Prerequisites
- Python 3.11+
- Virtual environment (included at `venv/`)
- ScrapingBee API key (pre-configured)
- OpenAI API key (required for Tier 2C + Tier 3)

### Activate environment and run server

```bash
# Windows
venv\Scripts\activate
python manage.py runserver

# or directly
venv/Scripts/python.exe manage.py runserver
```

### Create data directory

```bash
mkdir data
```

The pipeline auto-creates `data/ideas.ndjson` and `data/brand_analytics.sqlite3` on first use.

### Run system check

```bash
venv/Scripts/python.exe manage.py check
```

---

## 4. Environment Variables

All secrets are stored in `.env` at the project root. The file is loaded by each module independently using `_load_dotenv()`.

```env
# ── ScrapingBee (Amazon scraping) ─────────────────────────────────────────────
SCRAPINGBEE_API_KEY=your_key_here

# ── OpenAI (Tier 2C analysis + Tier 3 generation) ─────────────────────────────
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o           # Tier 2C — complex synthesis
OPENAI_MODEL_FAST=gpt-4o-mini # Tier 3 — structured generation (cheaper)

# ── Amazon SP-API (Brand Analytics ingestion) ─────────────────────────────────
SP_API_CLIENT_ID=
SP_API_CLIENT_SECRET=
SP_API_REFRESH_TOKEN=
SP_API_MARKETPLACE_ID=ATVPDKIKX0DER   # US marketplace

# ── AWS IAM (SP-API request signing) ─────────────────────────────────────────
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
```

> Only `SCRAPINGBEE_API_KEY` is required to run the Amazon search, product detail, and review scraping endpoints. The others are only needed for their respective features.

---

## 5. API Endpoints

Base URL: `http://localhost:8000/api/`

All request bodies are JSON. All responses are JSON.

---

### 5.1 Amazon Scraping

#### GET `/api/amazon-search/` — Search Amazon

Fetches the Amazon SERP for a keyword and returns structured product data.

**Query parameters:**

| Parameter | Required | Description |
|---|---|---|
| `keyword` | Yes | Search keyword, e.g. `bamboo travel mug` |
| `page` | No | Page number, default `1` |

**Request:**
```
GET /api/amazon-search/?keyword=bamboo+travel+mug&page=1
```

**Response:**
```json
{
    "keyword": "bamboo travel mug",
    "page": 1,
    "product_count": 16,
    "products": [
        {
            "asin": "B09XKPZL7Q",
            "title": "Bamboo Travel Mug 16oz — Eco Friendly Insulated",
            "price": 24.99,
            "rating": 4.3,
            "reviews": 1847,
            "sponsored": false,
            "badge": "Best Seller",
            "url": "https://www.amazon.com/dp/B09XKPZL7Q",
            "image_url": "https://..."
        }
    ]
}
```

---

#### GET `/api/amazon-product/` — Product Detail

Fetches full product details for a single ASIN.

**Query parameters:**

| Parameter | Required | Description |
|---|---|---|
| `asin` | Yes* | Amazon ASIN e.g. `B09XKPZL7Q` |
| `url` | Yes* | Full Amazon product URL (alternative to asin) |

*Either `asin` or `url` is required.

**Request:**
```
GET /api/amazon-product/?asin=B09XKPZL7Q
```

**Response:**
```json
{
    "asin": "B09XKPZL7Q",
    "product": {
        "asin": "B09XKPZL7Q",
        "title": "Bamboo Travel Mug 16oz — Eco Friendly",
        "brand": "EcoSip",
        "price": 24.99,
        "rating": 4.3,
        "review_count": 1847,
        "main_image_url": "https://...",
        "bullet_points": [
            "Made from natural bamboo fibre",
            "Double-wall insulation keeps drinks hot 6 hours"
        ],
        "listing_metadata": {
            "brand": "EcoSip",
            "availability": "In Stock",
            "best_seller_rank": "#4 in Travel Mugs"
        },
        "product_details": {
            "Item Weight": "0.35 Pounds",
            "Capacity": "16 Fluid Ounces"
        }
    }
}
```

---

### 5.2 Idea Memory

The idea memory store is the system's source of truth for all pipeline state. Every idea has a unique `idea_id` (UUID) and a `status` that tracks where it is in the pipeline.

**Valid statuses:** `new` → `scored` → `shortlisted` → `pre_sourcing` → `approved` / `dismissed`

---

#### POST `/api/ideas/create/` — Create Idea

Creates a new blank idea record.

**Request body:**
```json
{
    "keyword": "bamboo travel mug",
    "concept": "Eco-friendly commuter mug for sustainability-conscious buyers",
    "source": "human_seeded"
}
```

| Field | Required | Values |
|---|---|---|
| `keyword` | Yes | Amazon search keyword |
| `concept` | No | Free-text product description |
| `source` | No | `human_seeded` (default), `autonomous`, `adjacency_mining` |

**Response (HTTP 201):**
```json
{
    "idea_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "keyword": "bamboo travel mug",
    "concept": "Eco-friendly commuter mug",
    "source": "human_seeded",
    "status": "new",
    "created_at": "2026-06-01T10:00:00+00:00",
    "tier1_done": false,
    "reviews_scraped": false,
    ...
}
```

**Error (keyword already exists):**
```json
{
    "error": "Idea for keyword 'bamboo travel mug' already exists (idea_id=..., status=scored)."
}
```

---

#### GET `/api/ideas/` — List Ideas

Returns all ideas with optional filters.

**Query parameters (all optional):**

| Parameter | Example | Description |
|---|---|---|
| `status` | `scored` | Filter by pipeline status |
| `source` | `human_seeded` | Filter by entry source |
| `tier1_done` | `true` | Filter by Tier 1 completion |
| `reviews_scraped` | `false` | Filter by review scraping |
| `research_done` | `true` | Filter by AI research |
| `presourcing_done` | `false` | Filter by pre-sourcing |
| `has_flag` | `hard_kill` | Filter by flag presence |
| `min_tier1_score` | `60` | Minimum composite score |

**Request:**
```
GET /api/ideas/?status=shortlisted&min_tier1_score=60
```

**Response:**
```json
{
    "count": 3,
    "ideas": [
        { "idea_id": "...", "keyword": "bamboo travel mug", "tier1_score": 74, ... },
        { "idea_id": "...", "keyword": "silicone baby bib",  "tier1_score": 68, ... },
        { "idea_id": "...", "keyword": "desk cable organizer","tier1_score": 63, ... }
    ]
}
```

---

#### GET `/api/ideas/<idea_id>/` — Get One Idea

Returns the full record for a single idea.

**Request:**
```
GET /api/ideas/a1b2c3d4-e5f6-7890-abcd-ef1234567890/
```

**Response:** Full idea record (see [Idea Record Schema](#7-idea-record-schema))

**Error (not found):**
```json
{ "error": "Idea 'a1b2c3d4-...' not found" }
```

---

#### PATCH `/api/ideas/<idea_id>/update/` — Update Idea

Updates any field(s) on an existing idea. Dict fields are merged (not replaced).

**Request body (any subset of idea fields):**
```json
{
    "status": "shortlisted"
}
```

**To move to next pipeline stage (human gate):**
```json
{ "status": "shortlisted" }
```
```json
{ "status": "pre_sourcing" }
```
```json
{ "status": "approved" }
```
```json
{ "status": "dismissed" }
```

**To add a note:**
```json
{ "concept": "Updated product description after research" }
```

**Protected fields** (cannot be updated via API):
`idea_id`, `created_at`, `keyword`

**Response:** Full updated idea record.

---

### 5.3 Brand Analytics

Brand Analytics data is ingested weekly from Amazon SP-API into a local SQLite index. These endpoints query that index.

---

#### GET `/api/brand-analytics/lookup/` — Single Keyword Lookup

**Query parameters:**

| Parameter | Required | Description |
|---|---|---|
| `keyword` | Yes | Search term to look up |
| `report_date` | No | Specific period e.g. `2026-05` |

**Request:**
```
GET /api/brand-analytics/lookup/?keyword=bamboo+travel+mug
```

**Response (found):**
```json
{
    "keyword": "bamboo travel mug",
    "found": true,
    "data": {
        "search_term": "bamboo travel mug",
        "search_frequency_rank": 1423,
        "report_date": "2026-05",
        "clicked_asin_1": "B09XKPZL7Q",
        "click_share_1": 0.32,
        "conversion_share_1": 0.28,
        "clicked_asin_2": "B08MXYZ123",
        "click_share_2": 0.21,
        "conversion_share_2": 0.19,
        "clicked_asin_3": "B07ABCD456",
        "click_share_3": 0.14,
        "conversion_share_3": 0.11
    }
}
```

**Response (not found):**
```json
{
    "keyword": "bamboo travel mug",
    "found": false,
    "data": null
}
```

---

#### GET `/api/brand-analytics/lookup-batch/` — Batch Lookup

Look up up to 50 keywords in one request.

**Query parameters:**

| Parameter | Required | Description |
|---|---|---|
| `keywords` | Yes | Comma-separated list |
| `report_date` | No | Specific period |

**Request:**
```
GET /api/brand-analytics/lookup-batch/?keywords=bamboo+mug,silicone+bib,travel+cup
```

**Response:**
```json
{
    "queried": 3,
    "found": 2,
    "results": {
        "bamboo mug": { "search_frequency_rank": 1423, ... },
        "silicone bib": { "search_frequency_rank": 892, ... },
        "travel cup": null
    }
}
```

---

#### GET `/api/brand-analytics/status/` — Database Health

**Request:**
```
GET /api/brand-analytics/status/
```

**Response:**
```json
{
    "db_path": "/path/to/data/brand_analytics.sqlite3",
    "total_terms": 48231,
    "report_dates": ["2026-05", "2026-04"],
    "last_ingestion": {
        "report_date": "2026-05",
        "rows_inserted": 48231,
        "duration_seconds": 47.3,
        "completed_at": "2026-05-30T08:12:00+00:00"
    }
}
```

---

### 5.4 Tier 1 Scoring

Runs the full deterministic market scan and scoring pipeline for one keyword.

#### POST `/api/score/` — Score an Idea

**Request body:**

| Field | Required | Description |
|---|---|---|
| `keyword` | Yes* | Amazon search keyword |
| `idea_id` | Yes* | Use existing idea (alternative to keyword) |
| `concept` | No | Product description |
| `source` | No | Entry source (default: `human_seeded`) |
| `force_rescore` | No | Re-score even if already done (default: `false`) |

*Either `keyword` or `idea_id` is required.

**Request:**
```json
{
    "keyword": "bamboo travel mug",
    "concept": "Eco-friendly commuter mug",
    "source": "human_seeded"
}
```

**What Tier 1 does internally:**
1. Creates or loads the idea record
2. Checks cooldown (skips if on cooldown)
3. Checks if already scored (skips unless `force_rescore=true`)
4. Applies hard-kill keyword rules (instant dismiss, no scraping)
5. Fetches the Amazon SERP (1 scraping credit)
6. Looks up the keyword in Brand Analytics SQLite index
7. Fetches product detail pages for top 4 competitor ASINs (1 credit each)
8. Runs all 5 sub-scorers
9. Computes weighted composite score
10. Saves everything to idea memory
11. Applies cooldown if score < 45

**Response (scored):**
```json
{
    "status": "scored",
    "idea_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "keyword": "bamboo travel mug",
    "tier1_score": 74,
    "tier1_scores": {
        "demand": 80,
        "saturation": 65,
        "differentiation": 75,
        "fit": 100,
        "economic_viability": 70
    },
    "score_breakdown": {
        "demand": {
            "score": 80,
            "components": {
                "ba_rank_pts": 34,
                "organic_depth_pts": 16,
                "review_median_pts": 22,
                "sponsored_ratio_pts": 8
            },
            "flags": []
        },
        "saturation": { ... },
        "differentiation": { ... },
        "fit": { ... },
        "economic_viability": { ... }
    },
    "flags": ["strong_demand"],
    "eligible_for_tier15": true,
    "duration_seconds": 14.2
}
```

**Response (dismissed — hard kill):**
```json
{
    "status": "dismissed",
    "idea_id": "...",
    "keyword": "coffee mug",
    "tier1_score": 0,
    "flags": ["hard_kill"],
    "skip_reason": "Hard-kill keyword match: coffee",
    "duration_seconds": 0.01
}
```

**Response (skipped — on cooldown):**
```json
{
    "status": "skipped",
    "idea_id": "...",
    "keyword": "bamboo travel mug",
    "skip_reason": "Idea is on cooldown until 2026-06-08T10:00:00+00:00"
}
```

---

### 5.5 Tier 2A — Review Scraping

Scrapes Amazon customer reviews for the competitor products of a shortlisted idea.

**Prerequisite:** The idea must have `status = "shortlisted"` (set manually via the update endpoint). Tier 1 scoring must have run first so competitor ASINs are known.

#### POST `/api/reviews/scrape/` — Scrape Reviews

**Request body:**

| Field | Required | Description |
|---|---|---|
| `idea_id` | Yes | UUID of the shortlisted idea |
| `max_pages` | No | Review pages per ASIN, 1–10 (default: `3`, ~30 reviews per ASIN) |
| `max_asins` | No | Competitor ASINs to scrape, 1–5 (default: `3`) |
| `force` | No | Re-scrape if already done (default: `false`) |

**Request:**
```json
{
    "idea_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "max_pages": 3,
    "max_asins": 3
}
```

**What this does internally:**
1. Loads idea, checks status is `shortlisted`
2. Reads competitor ASINs from `tier1_evidence.competitor_asins`
3. For each ASIN: fetches up to `max_pages` review pages via ScrapingBee
4. Parses review text, rating, date, verified status, helpful votes
5. Saves raw reviews verbatim to `review_data.review_pages`
6. Sets `reviews_scraped = true`

**Response (complete):**
```json
{
    "status": "complete",
    "idea_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "keyword": "bamboo travel mug",
    "asins_scraped": ["B09XKPZL7Q", "B08MXYZ123", "B07ABCD456"],
    "total_reviews": 82,
    "review_counts": {
        "B09XKPZL7Q": 30,
        "B08MXYZ123": 28,
        "B07ABCD456": 24
    },
    "duration_seconds": 42.1,
    "warnings": []
}
```

**Response (skipped — wrong status):**
```json
{
    "status": "skipped",
    "idea_id": "...",
    "keyword": "bamboo travel mug",
    "skip_reason": "Idea status is 'scored'. Review scraping requires one of: shortlisted, pre_sourcing, approved."
}
```

---

### 5.6 Tier 2C — LLM Analysis

Runs GPT-4o synthesis of all evidence collected so far. Produces a structured customer insight and recommendation report.

**Prerequisite:** `tier1_done = true`. Quality improves significantly if `reviews_scraped = true` first.

#### POST `/api/analyse/` — Run Tier 2C Analysis

**Request body:**

| Field | Required | Description |
|---|---|---|
| `idea_id` | Yes | UUID of the idea |
| `force` | No | Re-run if already done (default: `false`) |

**Request:**
```json
{
    "idea_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**What GPT-4o analyses:**
- Top 8 SERP products (titles, prices, ratings, review counts)
- Brand Analytics rank and top-clicked competitors
- Competitor detail pages (bullets, features, brand)
- Up to 40 customer reviews (verbatim text)
- Research report (if available)

**The LLM is instructed to only draw conclusions from provided evidence. It must never invent market data.**

**Response (complete):**
```json
{
    "status": "complete",
    "idea_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "keyword": "bamboo travel mug",
    "recommendation": "Go",
    "analysis": {
        "voc_summary": "Buyers overwhelmingly prioritise leak-proof seals and genuine eco credentials. The current market leaders have strong brand recognition but consistently disappoint on lid quality and bamboo durability.",
        "pain_points": [
            "Lids crack or leak after 2–3 months",
            "Bamboo coating peels off",
            "Too wide to fit standard cup holders"
        ],
        "dealbreakers": [
            "Any leaking at all",
            "Smell from bamboo material"
        ],
        "usage_scenarios": [
            "Daily commute — needs to fit in car cup holder",
            "Office desk use — spill-proof when knocked over",
            "Hiking — lightweight and durable"
        ],
        "buyer_motivations": [
            "Reducing single-use plastic",
            "Gifting for eco-conscious family members"
        ],
        "end_user_avatar": "25–40 year old urban professional who cycles or takes public transport to work. Values sustainability but not at the cost of functionality.",
        "buyer_avatar": "Same as end user in 70% of cases. Gift buyers are typically parents or partners buying for eco-conscious household members.",
        "feature_blueprint": [
            { "feature": "360° leak-proof twist lid", "reason": "Top complaint across all reviewed products", "priority": "critical" },
            { "feature": "Slim 2.8\" base diameter", "reason": "Cup holder compatibility mentioned in 34% of reviews", "priority": "high" },
            { "feature": "Reinforced bamboo composite", "reason": "Peeling/cracking mentioned in 28% of 1-star reviews", "priority": "high" }
        ],
        "differentiation_strategy": "Enter at $27–32 price point with a lifetime lid warranty and cup-holder guarantee (exact dimensions on packaging). This directly attacks the two biggest failure modes of the current leaders.",
        "recommendation": "Go",
        "recommendation_reasoning": "Proven demand (BA rank 1423), clear whitespace on durability and fit, price band supports $5+ profit per unit at $29 retail. Reviews confirm buyers are actively switching products due to lid failures — the problem is real and unsolved."
    },
    "duration_seconds": 18.4
}
```

---

### 5.7 Tier 3 — Pre-Sourcing

Generates all pre-sourcing documents using GPT-4o-mini (3 separate LLM calls).

**Prerequisite:** Human must set `status = "pre_sourcing"` via the update endpoint.

#### POST `/api/presource/` — Run Tier 3 Generation

**Request body:**

| Field | Required | Description |
|---|---|---|
| `idea_id` | Yes | UUID of the idea |
| `force` | No | Re-run if already done (default: `false`) |

**Request:**
```json
{
    "idea_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**The 3 LLM calls:**

| Call | Purpose |
|---|---|
| Call 1 | Product concept + simulated buyer preference poll vs market leader |
| Call 2 | Amazon listing — title, 5 bullets, tagline, image shot list |
| Call 3 | Manufacturer sourcing spec — materials, dimensions, compliance, MOQ, Alibaba terms |

**Response (complete):**
```json
{
    "status": "complete",
    "idea_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "keyword": "bamboo travel mug",
    "presourcing_data": {
        "product_concept": "A 16oz double-wall bamboo fibre travel mug with a 360° twist-lock leak-proof lid (2.8\" base diameter for universal cup holder fit), reinforced inner liner, and a lifetime lid replacement guarantee.",
        "buyer_poll_setup": "Would you choose Product A (our concept) or Product B (EcoSip Bamboo Mug, 4.3★, 1847 reviews)?",
        "our_product_description": "360° twist-lock lid with lifetime guarantee, 2.8\" base fits all cup holders, reinforced bamboo composite — won't peel.",
        "competitor_description": "EcoSip Bamboo Mug — eco-friendly, popular, but reviewers report lid cracking and peeling bamboo coating.",
        "poll_winner": "our_product",
        "poll_reasoning": "Our product directly solves the two most-cited failure modes in reviews. The lifetime lid warranty eliminates the top purchase objection.",
        "poll_score": "8/10 simulated buyers chose our product",
        "listing_title": "Bamboo Travel Mug 16oz — 360° Leak-Proof Lid, Cup Holder Fit, Lifetime Lid Guarantee — Eco Friendly Double Wall Insulated Coffee Mug",
        "bullet_points": [
            "LIFETIME LID GUARANTEE — Our 360° twist-lock lid is engineered to never crack or leak. If it ever does, we replace it free. Forever.",
            "UNIVERSAL CUP HOLDER FIT — Precision 2.8\" base diameter fits every standard car, bike, and desk cup holder. No more balancing acts.",
            "REINFORCED BAMBOO COMPOSITE — Triple-layer bamboo fibre construction resists peeling and cracking for years of daily use.",
            "STAYS HOT 6 HOURS, COLD 12 — Double-wall vacuum insulation locks in temperature without the bulk of stainless steel.",
            "GENUINELY ECO FRIENDLY — Made from natural bamboo fibre, BPA-free lid, FSC-certified packaging. Better for the planet without the trade-offs."
        ],
        "tagline": "The mug that fixes everything you hate about bamboo mugs.",
        "image_shot_list": [
            "Hero: mug on white background, lid open showing 360° mechanism, 3/4 angle",
            "Lifestyle: mug in car cup holder — driver's hand on wheel, morning commute",
            "Technical: cross-section diagram showing double-wall construction and lid lock",
            "Scale: mug next to standard travel mug showing slim profile",
            "Infographic: 3 icons — Leak-Proof / Cup Holder Fit / Lifetime Guarantee"
        ],
        "materials_spec": "Outer shell: natural bamboo fibre composite (70% bamboo, 30% food-grade PP resin). Inner liner: food-grade 304 stainless steel. Lid: BPA-free Tritan plastic with silicone gasket seal.",
        "dimensions_assumptions": "Height: 185mm. Base diameter: 71mm (2.8\"). Opening diameter: 80mm. Capacity: 480ml / 16oz. Weight target: <320g.",
        "packaging_notes": "Kraft paper box with recycled inner sleeve. Retail-ready. Include lid guarantee card. Outer carton: 12 units. Master carton: 48 units.",
        "compliance_notes": "FDA food contact compliance required for US market. California Prop 65 warning if applicable. LFGB for EU. No BPA, phthalates, or heavy metals certification.",
        "quote_volume_assumptions": "Request quotes at 500 / 1000 / 3000 units. Target landed COGS ≤ $8.25 at 1000 units MOQ.",
        "supplier_search_terms": [
            "bamboo fibre travel mug manufacturer",
            "eco travel mug custom OEM",
            "bamboo coffee mug double wall insulated",
            "bamboo fiber reusable cup factory"
        ],
        "lead_time_assumptions": "Sample: 15–20 days. Production at 1000 units: 30–45 days. Sea freight to US: 25–35 days. Total pipeline: 70–100 days from PO to FBA."
    },
    "duration_seconds": 31.6
}
```

---

## 6. CLI Management Commands

All commands are run with the project's virtual environment Python:

```bash
venv/Scripts/python.exe manage.py <command> [options]
```

---

### Brand Analytics Ingestion

```bash
# Ingest last month's search terms report
python manage.py ingest_brand_analytics

# Specific date range
python manage.py ingest_brand_analytics --start-date 2026-05-01 --end-date 2026-05-31

# Dry run — validate credentials without writing to DB
python manage.py ingest_brand_analytics --dry-run
```

| Option | Description |
|---|---|
| `--start-date` | Report period start (YYYY-MM-DD) |
| `--end-date` | Report period end (YYYY-MM-DD) |
| `--period` | `WEEK` or `MONTH` (default: `MONTH`) |
| `--label` | Report date label stored in DB e.g. `2026-05` |
| `--dry-run` | Authenticate and request report but do not save |

---

### Tier 1 Scoring

```bash
# Score a new keyword
python manage.py score_idea --keyword "bamboo travel mug"

# Score with concept
python manage.py score_idea --keyword "bamboo travel mug" --concept "Eco commuter mug"

# Score an existing idea by ID
python manage.py score_idea --idea-id a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Force re-score
python manage.py score_idea --keyword "bamboo travel mug" --force

# Output as JSON
python manage.py score_idea --keyword "bamboo travel mug" --json
```

---

### Tier 2A — Review Scraping

```bash
# Scrape one idea (must be shortlisted)
python manage.py scrape_reviews --idea-id a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Scrape all pending shortlisted ideas
python manage.py scrape_reviews --all-pending

# More pages for deeper corpus
python manage.py scrape_reviews --idea-id <uuid> --max-pages 5 --max-asins 4

# Force re-scrape
python manage.py scrape_reviews --idea-id <uuid> --force

# JSON output
python manage.py scrape_reviews --all-pending --json
```

| Option | Default | Description |
|---|---|---|
| `--idea-id` | — | Single idea UUID |
| `--all-pending` | — | All shortlisted + not scraped |
| `--max-pages` | `3` | Review pages per ASIN (~10 reviews each) |
| `--max-asins` | `3` | Competitor ASINs to scrape |
| `--force` | `false` | Re-scrape if already done |
| `--json` | `false` | Print result as JSON |

---

### Tier 2C — LLM Analysis

```bash
# Analyse one idea
python manage.py run_tier2c --idea-id a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Analyse all shortlisted ideas with tier1_done=True
python manage.py run_tier2c --all-pending

# Force re-analyse
python manage.py run_tier2c --idea-id <uuid> --force

# JSON output
python manage.py run_tier2c --idea-id <uuid> --json
```

---

### Tier 3 — Pre-Sourcing

```bash
# Generate pre-sourcing docs for one idea
python manage.py run_tier3 --idea-id a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Generate for all ideas in pre_sourcing status
python manage.py run_tier3 --all-pending

# Force regenerate
python manage.py run_tier3 --idea-id <uuid> --force
```

---

## 7. Idea Record Schema

Every idea stored in `data/ideas.ndjson` has this exact structure.

```json
{
    "idea_id":   "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "keyword":   "bamboo travel mug",
    "concept":   "Eco-friendly commuter mug",
    "source":    "human_seeded",
    "created_at":"2026-06-01T10:00:00+00:00",
    "updated_at":"2026-06-01T12:30:00+00:00",
    "status":    "shortlisted",
    "cooldown_until": null,
    "flags":     ["strong_demand"],
    "task_board_id": null,

    "tier1_done": true,
    "tier1_at":   "2026-06-01T10:05:00+00:00",
    "tier1_score": 74,
    "tier1_scores": {
        "demand":             80,
        "saturation":         65,
        "differentiation":    75,
        "fit":                100,
        "economic_viability": 70
    },
    "tier1_evidence": {
        "serp_results":        [...],
        "competitor_asins":    ["B09X...", "B08M...", "B07A...", "B06Z..."],
        "competitor_details":  [...],
        "ba_search_terms":     [...],
        "price_band_low":      19.99,
        "price_band_high":     34.99,
        "review_count_median": 1423,
        "badge_count":         2,
        "sponsored_ratio":     0.25
    },

    "tier15_done": false,
    "tier15_at":   null,
    "tier15_data": { ... },

    "reviews_scraped":    true,
    "reviews_scraped_at": "2026-06-01T11:00:00+00:00",
    "review_data": {
        "products_reviewed": ["B09X...", "B08M...", "B07A..."],
        "review_pages": {
            "B09X...": [
                {
                    "review_id": "R1ABC123",
                    "title": "Great mug but lid leaked after 3 months",
                    "rating": 2.0,
                    "date": "Reviewed in the United States on May 1, 2026",
                    "text": "Love the bamboo design but the lid cracked...",
                    "verified_purchase": true,
                    "helpful_votes": 47
                }
            ]
        },
        "pain_points":      [],
        "use_cases":        [],
        "feature_requests": [],
        "buyer_objections": []
    },

    "research_done":    false,
    "research_done_at": null,
    "research_report":  "",
    "research_summary": { ... },

    "tier2_done": false,
    "tier2_at":   null,
    "tier2_analysis": {
        "voc_summary":             "",
        "pain_points":             [],
        "dealbreakers":            [],
        "usage_scenarios":         [],
        "buyer_motivations":       [],
        "end_user_avatar":         "",
        "buyer_avatar":            "",
        "feature_blueprint":       [],
        "differentiation_strategy":"",
        "recommendation":          ""
    },

    "presourcing_done": false,
    "presourcing_at":   null,
    "presourcing_data": {
        "product_concept":          "",
        "buyer_poll_result":        "",
        "listing_title":            "",
        "bullet_points":            [],
        "tagline":                  "",
        "image_shot_list":          [],
        "materials_spec":           "",
        "dimensions_assumptions":   "",
        "packaging_notes":          "",
        "compliance_notes":         "",
        "quote_volume_assumptions": "",
        "supplier_search_terms":    [],
        "lead_time_assumptions":    ""
    }
}
```

### Valid status transitions

```
new → scored → shortlisted → pre_sourcing → approved
                                          → dismissed
```

A human must manually move:
- `scored` → `shortlisted` (via PATCH update endpoint)
- `shortlisted` → `pre_sourcing` (via PATCH update endpoint)

The system handles every other transition automatically.

---

## 8. Scoring System

Tier 1 scores are deterministic — no LLM, no randomness. The same input always produces the same output.

### Composite score formula

```
composite = (demand × 0.35) + (saturation × 0.25) + (differentiation × 0.20)
          + (fit × 0.10) + (economic_viability × 0.10)
```

**Special rule:** If `fit = 0` (hard-kill triggered), `composite = 0` regardless of other scores.

### Sub-score breakdown

#### Demand (0–100)
Measures how much genuine search volume and buyer intent exists.

| Component | Max pts | Source |
|---|---|---|
| BA search frequency rank | 40 | Brand Analytics SQLite |
| Organic SERP result depth | 20 | Amazon SERP |
| Median competitor review count | 30 | Amazon SERP |
| Sponsored ad ratio (inverse) | 10 | Amazon SERP |

If no Brand Analytics data exists for the keyword, the remaining 3 components are rescaled to fill 100 points and a `no_ba_data` flag is added.

#### Saturation (0–100)
Measures ease of entry — higher score means easier to enter.

| Component | Max pts | What it measures |
|---|---|---|
| High-review competitor density | 35 | Fewer entrenched competitors = higher score |
| Best Seller / Choice badge count | 25 | Fewer badges = less locked-in |
| BA click share concentration | 25 | Distributed clicks = more opportunity |
| Price band tightness | 15 | Wider band = more room to position |

#### Differentiation (0–100)
Measures whether a gap exists to exploit.

| Component | Max pts | What it measures |
|---|---|---|
| Price gap above market median | 35 | Room to sell at a premium |
| Rating ceiling gap | 30 | Headroom above current best rating |
| Brand diversity | 20 | Many brands = no dominant player |
| Feature whitespace from bullets | 15 | Gaps in competitor feature coverage |

#### Fit (0–100)
Measures whether this idea is viable to source and sell via FBA.

| Check | Points | Rule |
|---|---|---|
| Hard-kill keyword | 0 (instant) | Matches HARD_KILL_KEYWORD_PATTERNS |
| Hard-kill SERP titles | 0 (instant) | ≥60% of top-10 titles match HARD_KILL_TITLE_PATTERNS |
| Price viability | 50 | Price between $15 and $80 |
| Price ceiling | 20 | Price ≤ $80 practical sourcing ceiling |
| FBA-friendly category | 30 | Keyword contains FBA-friendly category signal |

#### Economic Viability (0–100)
Estimates whether unit economics work at the observed price point.

```
profit_per_unit = price - (price × 15%) - $4.50 FBA fee - (price × 33% COGS)

Minimum required: $5.00 profit per unit
Minimum category revenue: $3,000/month
```

| Component | Max pts | Rule |
|---|---|---|
| Profit per unit after fees | 60 | ≥$5 required; scales with margin |
| Estimated monthly category revenue | 40 | review_count × 0.05 × price |

### Hard-kill categories

Ideas with keywords matching these patterns are instantly dismissed before any scraping:
- Digital/media: `book`, `kindle`, `music`, `dvd`, `software`, `gift card`
- Food/consumables: `coffee`, `tea`, `supplement`, `vitamin`, `snack`
- Regulated: `tobacco`, `alcohol`, `firearm`, `pharmaceutical`
- Livestock: `live animal`, `live plant`

---

## 9. Configuration Reference

All scoring constants are in [api/scoring/config.py](api/scoring/config.py).

| Constant | Default | Description |
|---|---|---|
| `TIER1_MINIMUM_SCORE` | `45` | Below → dismissed |
| `TIER1_TASK_THRESHOLD` | `55` | Above → task board entry |
| `TIER1_5_THRESHOLD` | `70` | Above → Tier 1.5 eligible |
| `COOLDOWN_HOURS_LOW_SCORE` | `168` | 7 days for below-minimum ideas |
| `COOLDOWN_HOURS_DISMISSED` | `720` | 30 days for hard-killed ideas |
| `MAX_COMPETITOR_DETAILS` | `4` | Detail pages fetched per idea |
| `AMAZON_REFERRAL_FEE_RATE` | `0.15` | 15% referral fee |
| `FBA_FULFILLMENT_FEE_AVG` | `$4.50` | Average FBA fulfillment fee |
| `COGS_TARGET_RATIO` | `0.33` | COGS ≤ 33% of selling price |
| `MIN_PROFIT_PER_UNIT` | `$5.00` | Minimum margin to pass |
| `MIN_VIABLE_PRICE` | `$15.00` | Below this → margins impossible |
| `MAX_PRACTICAL_PRICE` | `$80.00` | Above this → sourcing too complex |
| `MIN_MONTHLY_REVENUE` | `$3,000` | Minimum category revenue |

Django settings in [npdapi/settings.py](npdapi/settings.py):

| Setting | Value |
|---|---|
| `IDEA_MEMORY_PATH` | `BASE_DIR/data/ideas.ndjson` |
| `BA_DB_PATH` | `BASE_DIR/data/brand_analytics.sqlite3` |

---

## 10. Project Structure

```
NPD-api/
├── manage.py
├── .env                          ← All secrets (never commit)
├── Document.md                   ← This file
├── npd_flow_technical_overview.md← Pipeline design reference
├── data/
│   ├── ideas.ndjson              ← Idea memory store (auto-created)
│   └── brand_analytics.sqlite3   ← BA keyword index (populated by ingest)
│
├── npdapi/
│   ├── settings.py               ← Django settings + IDEA_MEMORY_PATH, BA_DB_PATH
│   └── urls.py                   ← Routes /api/ to api/urls.py
│
└── api/
    ├── views.py                  ← All REST endpoint handlers
    ├── urls.py                   ← All URL patterns
    │
    ├── search/                   ← Amazon SERP scraping
    │   ├── scraper.py            ← fetch_amazon_search()
    │   └── parser.py             ← parse_amazon_results()
    │
    ├── product/                  ← Amazon product detail scraping
    │   ├── scraper.py            ← fetch_amazon_product()
    │   └── parser.py             ← parse_amazon_product()
    │
    ├── memory/                   ← NDJSON idea store
    │   ├── schema.py             ← build_default_idea(), VALID_STATUSES
    │   └── store.py              ← IdeaMemoryStore (create/get/update/filter)
    │
    ├── brand_analytics/          ← SP-API Brand Analytics
    │   ├── spapi_client.py       ← LWA auth, SigV4 signing, report download
    │   ├── db.py                 ← SQLite index (init/insert/lookup)
    │   ├── ingestion.py          ← run_ingestion() orchestrator
    │   └── management/commands/
    │       └── ingest_brand_analytics.py
    │
    ├── scoring/                  ← Tier 1 deterministic scoring
    │   ├── config.py             ← All weights, thresholds, constants
    │   ├── sub_scores.py         ← 5 pure scoring functions
    │   ├── scorer.py             ← score_idea() full pipeline
    │   └── management/commands/
    │       └── score_idea.py
    │
    ├── reviews/                  ← Tier 2A review scraping
    │   ├── scraper.py            ← fetch_amazon_reviews()
    │   ├── parser.py             ← parse_amazon_reviews(), has_next_page()
    │   ├── job.py                ← run_review_scraping()
    │   └── management/commands/
    │       └── scrape_reviews.py
    │
    └── llm/                      ← Tier 2C + Tier 3 LLM layer
        ├── client.py             ← OpenAI wrapper, JSON mode, retry
        ├── tier2c.py             ← run_tier2c() — GPT-4o analysis
        ├── tier3.py              ← run_tier3() — GPT-4o-mini generation
        └── management/commands/
            ├── run_tier2c.py
            └── run_tier3.py
```

---

## Quick Start — End-to-End Example

```bash
# 1. Check setup
python manage.py check

# 2. (Weekly) Ingest Brand Analytics
python manage.py ingest_brand_analytics

# 3. Score a new product idea
python manage.py score_idea --keyword "bamboo travel mug" --json

# 4. [HUMAN] Review score — if good, shortlist via API:
#    PATCH /api/ideas/<idea_id>/update/  {"status": "shortlisted"}

# 5. Scrape competitor reviews
python manage.py scrape_reviews --idea-id <uuid>

# 6. Run GPT-4o analysis
python manage.py run_tier2c --idea-id <uuid>

# 7. [HUMAN] Review analysis — if approved, move to pre-sourcing:
#    PATCH /api/ideas/<idea_id>/update/  {"status": "pre_sourcing"}

# 8. Generate pre-sourcing documents
python manage.py run_tier3 --idea-id <uuid>

# 9. Retrieve the complete idea record
#    GET /api/ideas/<idea_id>/
```
