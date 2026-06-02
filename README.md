# NPD API — Complete Documentation

**New Product Discovery pipeline API built with Django 6 + Django REST Framework + MongoDB.**

Automates the discovery, validation, and pre-sourcing of Amazon FBA product ideas from raw keyword signals all the way through to a manufacturer-ready sourcing specification.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture & Pipeline Flow](#2-architecture--pipeline-flow)
3. [Setup & Installation](#3-setup--installation)
   - [Option A — Docker (recommended)](#option-a--docker-recommended)
   - [Option B — Local development](#option-b--local-development)
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
- Django 6.0.5 (no ORM — no SQL database)
- Django REST Framework 3.17.1
- **MongoDB 7.0** (primary database — ideas, brand analytics, ingestion logs)
- **pymongo 4.17.0** (MongoDB driver)
- OpenAI API (`gpt-4o` + `gpt-4o-mini`)
- ScrapingBee API (Amazon SERP, product detail, reviews)
- Amazon SP-API (Brand Analytics reports)
- Docker + Docker Compose (containerised deployment)

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

### MongoDB collections

| Collection | Contents |
|---|---|
| `ideas` | All product idea records (one document per idea) |
| `ba_search_terms` | Brand Analytics keyword rows from Amazon SP-API reports |
| `ba_ingestion_log` | Audit trail of Brand Analytics ingestion runs |

---

## 3. Setup & Installation

### Option A — Docker (recommended)

The fastest way to run the full stack with zero local Python setup required.

**Prerequisites:** Docker Desktop installed and running.

```bash
# 1. Clone the repo and enter the directory
cd NPD-api

# 2. Copy the example env file and fill in your API keys
#    (SCRAPINGBEE_API_KEY and OPENAI_API_KEY are required)
#    MongoDB credentials are pre-configured in docker-compose.yml

# 3. Start everything
docker compose up -d

# 4. Verify both containers are healthy
docker compose ps
```

**Expected output:**
```
NAME          IMAGE         STATUS
npd_mongodb   mongo:7.0     Up (healthy)
npd_web       npd-api-web   Up
```

The API is available at `http://localhost:8000`.
MongoDB is available at `localhost:27017`.

**Container management:**

```bash
# Start
docker compose up -d

# Stop (keeps MongoDB data)
docker compose down

# Stop + delete all data
docker compose down -v

# View Django logs
docker compose logs -f web

# View MongoDB logs
docker compose logs -f mongodb

# Rebuild after code changes
docker compose build && docker compose up -d

# Open a shell inside the web container
docker exec -it npd_web sh

# Connect to MongoDB directly
docker exec -it npd_mongodb mongosh \
  "mongodb://npduser:npdpassword@localhost:27017/npd_db?authSource=admin"
```

---

### Option B — Local development

**Prerequisites:**
- Python 3.11+
- MongoDB 7.0 running locally on port 27017 (no auth required for local dev)

```bash
# 1. Activate the virtual environment
# Windows
venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create the data directory
mkdir data

# 4. Run the dev server
python manage.py runserver
```

The `.env` file ships with `MONGO_URI=mongodb://localhost:27017/npd_db` so local MongoDB (without authentication) works out of the box.

**Run system check:**
```bash
python manage.py check
```

---

## 4. Environment Variables

All secrets are stored in `.env` at the project root. The file is loaded by each module independently using `_load_dotenv()`.

```env
# ── MongoDB ───────────────────────────────────────────────────────────────────
# Local dev: unauthenticated localhost (default below)
# Docker: overridden automatically by docker-compose.yml
MONGO_URI=mongodb://localhost:27017/npd_db
MONGO_DB=npd_db

# ── ScrapingBee (Amazon scraping) ─────────────────────────────────────────────
SCRAPINGBEE_API_KEY=your_key_here

# ── OpenAI (Tier 2C analysis + Tier 3 generation) ─────────────────────────────
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
OPENAI_MODEL_FAST=gpt-4o-mini

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

> **Note:** `MONGO_URI` and `MONGO_DB` are automatically overridden by `docker-compose.yml` when running in Docker. The local values are only used for direct `python manage.py runserver` runs.

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

The idea memory store is the system's source of truth for all pipeline state. Every idea is a MongoDB document in the `ideas` collection with a unique `idea_id` (UUID) and a `status` that tracks where it is in the pipeline.

**Valid statuses:** `new` → `scored` → `shortlisted` → `pre_sourcing` → `approved` / `dismissed`

---

#### POST `/api/ideas/create/` — Create Idea

Creates a new blank idea document in MongoDB.

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

Returns all ideas with optional filters (queries MongoDB `ideas` collection).

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

Returns the full MongoDB document for a single idea.

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

**Protected fields** (cannot be updated via API):
`idea_id`, `created_at`, `keyword`

**Response:** Full updated idea record.

---

### 5.3 Brand Analytics

Brand Analytics data is ingested from Amazon SP-API into the MongoDB `ba_search_terms` collection. These endpoints query that collection.

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
    "total_terms": 48231,
    "report_dates": ["2026-05", "2026-04"],
    "last_ingestion": {
        "report_date": "2026-05",
        "rows_inserted": 48231,
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
1. Creates or loads the idea document from MongoDB
2. Checks cooldown (skips if on cooldown)
3. Checks if already scored (skips unless `force_rescore=true`)
4. Applies hard-kill keyword rules (instant dismiss, no scraping)
5. Fetches the Amazon SERP (1 scraping credit)
6. Looks up the keyword in MongoDB `ba_search_terms` collection
7. Fetches product detail pages for top 4 competitor ASINs (1 credit each)
8. Runs all 5 sub-scorers
9. Computes weighted composite score
10. Saves everything to MongoDB `ideas` collection
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

---

### 5.5 Tier 2A — Review Scraping

Scrapes Amazon customer reviews for the competitor products of a shortlisted idea.

**Prerequisite:** The idea must have `status = "shortlisted"`.

#### POST `/api/reviews/scrape/` — Scrape Reviews

**Request body:**

| Field | Required | Description |
|---|---|---|
| `idea_id` | Yes | UUID of the shortlisted idea |
| `max_pages` | No | Review pages per ASIN, 1–10 (default: `3`) |
| `max_asins` | No | Competitor ASINs to scrape, 1–5 (default: `3`) |
| `force` | No | Re-scrape if already done (default: `false`) |

**Response (complete):**
```json
{
    "status": "complete",
    "idea_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "keyword": "bamboo travel mug",
    "asins_scraped": ["B09XKPZL7Q", "B08MXYZ123", "B07ABCD456"],
    "total_reviews": 82,
    "duration_seconds": 42.1
}
```

---

### 5.6 Tier 2C — LLM Analysis

Runs GPT-4o synthesis of all evidence. Produces a structured customer insight and recommendation report.

**Prerequisite:** `tier1_done = true`. Quality improves significantly if `reviews_scraped = true` first.

#### POST `/api/analyse/` — Run Tier 2C Analysis

**Request body:**

| Field | Required | Description |
|---|---|---|
| `idea_id` | Yes | UUID of the idea |
| `force` | No | Re-run if already done (default: `false`) |

**Response (complete):**
```json
{
    "status": "complete",
    "idea_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "keyword": "bamboo travel mug",
    "recommendation": "Go",
    "analysis": {
        "voc_summary": "...",
        "pain_points": ["Lids crack after 2–3 months", "Bamboo coating peels"],
        "dealbreakers": ["Any leaking at all"],
        "feature_blueprint": [
            { "feature": "360° leak-proof lid", "reason": "Top complaint", "priority": "critical" }
        ],
        "differentiation_strategy": "...",
        "recommendation": "Go",
        "recommendation_reasoning": "..."
    },
    "duration_seconds": 18.4
}
```

---

### 5.7 Tier 3 — Pre-Sourcing

Generates all pre-sourcing documents using GPT-4o-mini (3 separate LLM calls).

**Prerequisite:** Human must set `status = "pre_sourcing"`.

#### POST `/api/presource/` — Run Tier 3 Generation

**Request body:**

| Field | Required | Description |
|---|---|---|
| `idea_id` | Yes | UUID of the idea |
| `force` | No | Re-run if already done (default: `false`) |

**Response (complete):**
```json
{
    "status": "complete",
    "idea_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "keyword": "bamboo travel mug",
    "presourcing_data": {
        "listing_title": "Bamboo Travel Mug 16oz — 360° Leak-Proof Lid...",
        "bullet_points": ["LIFETIME LID GUARANTEE — ...", "..."],
        "tagline": "The mug that fixes everything you hate about bamboo mugs.",
        "image_shot_list": [
            { "shot": "Hero shot", "description": "Mug on white background", "purpose": "Main listing image" }
        ],
        "materials_spec": "Outer: bamboo fibre composite. Inner: 304 stainless steel.",
        "supplier_search_terms": ["bamboo fibre travel mug manufacturer", "..."],
        "lead_time_assumptions": "Sample: 15–20 days. Production: 30–45 days."
    },
    "duration_seconds": 31.6
}
```

---

## 6. CLI Management Commands

All commands can be run inside Docker or with the local virtual environment.

**Inside Docker:**
```bash
docker exec npd_web python manage.py <command> [options]
```

**Local dev:**
```bash
venv\Scripts\python.exe manage.py <command> [options]
```

---

### Brand Analytics Ingestion

```bash
# Ingest last month's search terms report
python manage.py ingest_brand_analytics

# Specific date range
python manage.py ingest_brand_analytics --start-date 2026-05-01 --end-date 2026-05-31

# Dry run — validate credentials without writing to MongoDB
python manage.py ingest_brand_analytics --dry-run
```

| Option | Description |
|---|---|
| `--start-date` | Report period start (YYYY-MM-DD) |
| `--end-date` | Report period end (YYYY-MM-DD) |
| `--period` | `WEEK` or `MONTH` (default: `MONTH`) |
| `--label` | Report date label stored in MongoDB e.g. `2026-05` |
| `--dry-run` | Authenticate and request report but do not save |

---

### Tier 1 Scoring

```bash
python manage.py score_idea --keyword "bamboo travel mug"
python manage.py score_idea --keyword "bamboo travel mug" --concept "Eco commuter mug"
python manage.py score_idea --idea-id a1b2c3d4-e5f6-7890-abcd-ef1234567890
python manage.py score_idea --keyword "bamboo travel mug" --force
python manage.py score_idea --keyword "bamboo travel mug" --json
```

---

### Tier 2A — Review Scraping

```bash
python manage.py scrape_reviews --idea-id a1b2c3d4-e5f6-7890-abcd-ef1234567890
python manage.py scrape_reviews --all-pending
python manage.py scrape_reviews --idea-id <uuid> --max-pages 5 --max-asins 4
python manage.py scrape_reviews --idea-id <uuid> --force
```

| Option | Default | Description |
|---|---|---|
| `--idea-id` | — | Single idea UUID |
| `--all-pending` | — | All shortlisted + not scraped |
| `--max-pages` | `3` | Review pages per ASIN (~10 reviews each) |
| `--max-asins` | `3` | Competitor ASINs to scrape |
| `--force` | `false` | Re-scrape if already done |

---

### Tier 2C — LLM Analysis

```bash
python manage.py run_tier2c --idea-id a1b2c3d4-e5f6-7890-abcd-ef1234567890
python manage.py run_tier2c --all-pending
python manage.py run_tier2c --idea-id <uuid> --force
python manage.py run_tier2c --idea-id <uuid> --json
```

---

### Tier 3 — Pre-Sourcing

```bash
python manage.py run_tier3 --idea-id a1b2c3d4-e5f6-7890-abcd-ef1234567890
python manage.py run_tier3 --all-pending
python manage.py run_tier3 --idea-id <uuid> --force
```

---

## 7. Idea Record Schema

Every idea is stored as a MongoDB document in the `ideas` collection with this structure.

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

| Component | Max pts | Source |
|---|---|---|
| BA search frequency rank | 40 | MongoDB `ba_search_terms` |
| Organic SERP result depth | 20 | Amazon SERP |
| Median competitor review count | 30 | Amazon SERP |
| Sponsored ad ratio (inverse) | 10 | Amazon SERP |

#### Saturation (0–100)

| Component | Max pts | What it measures |
|---|---|---|
| High-review competitor density | 35 | Fewer entrenched competitors = higher score |
| Best Seller / Choice badge count | 25 | Fewer badges = less locked-in |
| BA click share concentration | 25 | Distributed clicks = more opportunity |
| Price band tightness | 15 | Wider band = more room to position |

#### Differentiation (0–100)

| Component | Max pts | What it measures |
|---|---|---|
| Price gap above market median | 35 | Room to sell at a premium |
| Rating ceiling gap | 30 | Headroom above current best rating |
| Brand diversity | 20 | Many brands = no dominant player |
| Feature whitespace from bullets | 15 | Gaps in competitor feature coverage |

#### Fit (0–100)

| Check | Points | Rule |
|---|---|---|
| Hard-kill keyword | 0 (instant) | Matches HARD_KILL_KEYWORD_PATTERNS |
| Hard-kill SERP titles | 0 (instant) | ≥60% of top-10 titles match patterns |
| Price viability | 50 | Price between $15 and $80 |
| Price ceiling | 20 | Price ≤ $80 practical sourcing ceiling |
| FBA-friendly category | 30 | Keyword contains FBA-friendly signal |

#### Economic Viability (0–100)

```
profit_per_unit = price - (price × 15%) - $4.50 FBA fee - (price × 33% COGS)

Minimum required: $5.00 profit per unit
Minimum category revenue: $3,000/month
```

### Hard-kill categories

Ideas with keywords matching these patterns are instantly dismissed:
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

Django / MongoDB settings in [npdapi/settings.py](npdapi/settings.py):

| Setting | Value | Description |
|---|---|---|
| `MONGO_URI` | `MONGO_URI` env var | MongoDB connection string |
| `MONGO_DB` | `MONGO_DB` env var | Database name (default: `npd_db`) |
| `IDEA_MEMORY_PATH` | *(legacy — ignored)* | Kept for backward compatibility |
| `BA_DB_PATH` | *(legacy — ignored)* | Kept for backward compatibility |

---

## 10. Project Structure

```
NPD-api/
├── manage.py
├── .env                          ← All secrets (never commit)
├── Dockerfile                    ← Docker image build instructions
├── docker-compose.yml            ← MongoDB + web service orchestration
├── .dockerignore                 ← Files excluded from Docker image
├── requirements.txt              ← All pinned Python dependencies
├── README.md                     ← This file
│
├── npdapi/
│   ├── settings.py               ← Django settings + MONGO_URI, MONGO_DB
│   └── urls.py                   ← Routes /api/ → api/urls.py
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
    ├── memory/                   ← MongoDB idea store
    │   ├── schema.py             ← build_default_idea(), VALID_STATUSES
    │   └── store.py              ← IdeaMemoryStore (MongoDB-backed)
    │
    ├── brand_analytics/          ← SP-API Brand Analytics
    │   ├── spapi_client.py       ← LWA auth, SigV4 signing, report download
    │   ├── db.py                 ← MongoDB ba_search_terms (init/insert/lookup)
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
    │   ├── parser.py             ← parse_amazon_reviews()
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
# 1. Start the stack
docker compose up -d

# 2. (Weekly) Ingest Brand Analytics into MongoDB
docker exec npd_web python manage.py ingest_brand_analytics

# 3. Score a new product idea
docker exec npd_web python manage.py score_idea --keyword "bamboo travel mug" --json

# 4. [HUMAN] Review score — if good, shortlist via API:
#    PATCH /api/ideas/<idea_id>/update/  {"status": "shortlisted"}

# 5. Scrape competitor reviews
docker exec npd_web python manage.py scrape_reviews --idea-id <uuid>

# 6. Run GPT-4o analysis
docker exec npd_web python manage.py run_tier2c --idea-id <uuid>

# 7. [HUMAN] Review analysis — if approved, move to pre-sourcing:
#    PATCH /api/ideas/<idea_id>/update/  {"status": "pre_sourcing"}

# 8. Generate pre-sourcing documents
docker exec npd_web python manage.py run_tier3 --idea-id <uuid>

# 9. Retrieve the complete idea record
#    GET /api/ideas/<idea_id>/

# 10. Inspect data directly in MongoDB
docker exec -it npd_mongodb mongosh \
  "mongodb://npduser:npdpassword@localhost:27017/npd_db?authSource=admin" \
  --eval "db.ideas.find({}, {idea_id:1, keyword:1, status:1, tier1_score:1}).pretty()"
```
