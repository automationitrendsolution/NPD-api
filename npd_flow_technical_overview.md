# NPD Flow — High-Level Technical Overview

## Purpose

The NPD system is a product discovery and validation pipeline. It identifies product ideas, validates demand and competition, enriches strong ideas with deeper market/customer data, then packages the best candidates for human sourcing review.

It does **not** directly launch or source products. Its role is to turn raw market signals into validated product opportunities.

---

## High-Level Flow

```text
Discovery inputs
  ↓
Tier 1: Market scan + deterministic scoring
  ↓
Product discovery task created
  ↓
Tier 1.5: External market enrichment for strong ideas
  ↓
Human shortlists idea
  ↓
Tier 2: Review scraping + deep research + customer insight
  ↓
Human moves idea to pre-sourcing
  ↓
Tier 3: Buyer poll + listing draft + sourcing spec
  ↓
Human approves or dismisses
  ↓
Sourcing begins outside NPD
```

---

## Data Sources and API Points

The NPD pipeline uses several distinct data sources. Each source has a specific role in the workflow and is ingested at a different cadence.

| Data source | API / access point | Ingested data | When used | Purpose |
|---|---|---|---|---|
| Amazon marketplace search results | Scraping API using Amazon search URLs, parsed with an Amazon keyword/search parser | Keyword SERPs, ranked products, prices, ratings, review counts, sponsored status, badges, titles, images | Tier 1, on each idea evaluation | Measures live market structure, competition, price bands, and initial demand |
| Amazon product detail pages | Scraping API using Amazon product detail URLs, parsed with product-detail parser | Product title, price, rating, review count, listing metadata, product details | Tier 1 and Tier 2 | Provides competitor product evidence and detail enrichment |
| Amazon reviews | Scraping API using Amazon review parser | Review text, ratings, review pages, product review corpus | Tier 2, after human shortlist | Extracts customer pain points, objections, use cases, and desired features |
| Brand Analytics search terms | Amazon SP-API Reports API: `GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT` | Search terms, frequency rank, top-clicked products, click share, conversion share | Weekly ingestion, then queried during Tier 1 | Validates search demand and identifies top clicked competitor products |
| Brand Analytics market basket | Amazon SP-API Brand Analytics / Market Basket report | Co-purchased products and product adjacency | Weekly / cached ingestion | Finds adjacent product opportunities and bundle/complement signals |
| Brand Analytics catalog performance | Amazon SP-API Brand Analytics / Catalog Performance report | Owned product funnel/performance context | Periodic ingestion | Provides context, but is not the main NPD scoring source |
| Brand Analytics repeat purchase | Amazon SP-API Brand Analytics / Repeat Purchase report | Repeat purchase behaviour by product | Periodic ingestion | Provides context for product/category quality, not core scoring |
| Product discovery task board | Task management API | Product ideas, statuses, comments, human decisions, approvals, dismissals | Event-driven + daily sync | Acts as the human-facing system of record |
| Local idea memory | Local structured file/database, typically NDJSON/JSON | Idea state, scores, flags, cooldowns, evidence, workflow completion markers | Read/write throughout every job | Prevents duplicates, tracks workflow state, manages budget and recovery |
| External market intelligence tool | External API: niche creation, niche status, competitor detail, keyword list, delete niche | Opportunity evaluation, competitor benchmarks, niche structure, keyword opportunities | Tier 1.5, every few hours for strong ideas | Enriches strong ideas with additional third-party market context |
| AI deep research | Browser/API automation against an AI research tool | Market research report, competitor framing, trends, customer segments, risks | Tier 2, after human shortlist | Adds broader strategic context to review and marketplace evidence |
| LLM analysis layer | LLM API/session runtime | Summaries, buyer avatars, product blueprint, recommendation, listing/spec drafts | Tier 2 and Tier 3 | Synthesises evidence; does not replace raw data retrieval |
| Scheduled job runner | Cron / workflow scheduler | Job triggers and run history | Across all stages | Runs recurring ingestion, scoring, scraping, enrichment, and reporting |

---

## API / Integration Detail by Stage

### Discovery Inputs

Product ideas enter the system through three routes:

1. **Autonomous discovery**
   - Reads previously generated Brand Analytics adjacency output.
   - Reads local brand/category fit rules.
   - Uses LLM ideation to generate candidate product hypotheses.
   - Validates candidate keywords against the local Brand Analytics search index before spending scrape credits.

2. **Human-seeded ideas**
   - A person adds a product concept to the product discovery task board.
   - A daily sync pulls unscored tasks from the task board API.
   - The system parses the concept, generates likely search keywords, and runs Tier 1.

3. **Brand Analytics adjacency mining**
   - Uses search-term and market-basket data to find adjacent categories or products.
   - Output is saved as a structured discovery file and consumed by autonomous discovery runs.

---

## Tier 1 — Market Scan and Scoring

Tier 1 is the first gate. It is designed to be relatively cheap and deterministic.

### API points used

| Step | API / tool | What happens |
|---|---|---|
| Existing market lookup | Internal market intelligence script | Checks whether there is already recent scan data for the idea/category |
| Brand/fit hard-kill | Local config + deterministic script | Rejects obvious non-fits before spending external credits |
| Marketplace SERP scan | Scraping API with Amazon keyword/search parser | Pulls live search results for each keyword, one keyword per call |
| Product detail extraction | Scraping API with Amazon product-detail parser | Pulls details for selected competitor products when needed |
| Search demand validation | Local SQLite index built from SP-API Brand Analytics reports | Looks up matching search terms, frequency rank, clicked products, click/conversion share |
| Deterministic scoring | Local scoring script | Computes demand, saturation, differentiation, fit, and economic viability |
| Task creation/update | Task management API | Creates or updates the product discovery task if the score passes threshold |

### Data used in scoring

| Score area | Source data |
|---|---|
| Demand | Marketplace result depth, organic density, review volume, Brand Analytics search frequency rank, related keyword count |
| Saturation | Number of high-review competitors, badge concentration, price clustering, dominant incumbents |
| Differentiation | Premium price gaps, feature/material whitespace, review pain points where available |
| Fit | Category fit, materials fit, price viability, supply-chain plausibility |
| Economic viability | Estimated retail price, fee assumptions, COGS allowance, minimum profit/unit, minimum monthly revenue |

Brand Analytics demand is weighted heavily because it reflects actual search behaviour over a reporting period. Live marketplace scans are still used because they reveal current competition and pricing.

---

## Brand Analytics Ingestion

Brand Analytics is ingested separately from normal product scoring because the reports are large.

### Search Terms ingestion flow

```text
SP-API Reports request
  ↓
Create Brand Analytics Search Terms report
  ↓
Poll report status until complete
  ↓
Download report document
  ↓
Decompress if required
  ↓
Parse search-term rows
  ↓
Write rows into local SQLite database
  ↓
Index search_term, frequency_rank, clicked_product
  ↓
Use local lookup during Tier 1 scoring
```

### Stored fields

Typical indexed fields include:

- Search term
- Search frequency rank
- Clicked product identifier
- Click share rank
- Click share
- Conversion share

### Why this is local-indexed

The raw report can be large, so the system does not call SP-API for every idea. Instead, it builds a local database on a weekly cadence and performs fast keyword lookups during NPD scoring.

---

## Tier 1.5 — External Market Enrichment

Tier 1.5 runs only for stronger Tier 1 ideas.

### API points used

| API point | Purpose |
|---|---|
| Create niche/dive endpoint | Starts an external market analysis from a representative competitor product |
| Dive status endpoint | Polls until the analysis is complete |
| Niche competitors endpoint | Retrieves competitor benchmark data |
| Niche keyword list endpoint | Retrieves keyword and launch-opportunity data |
| Delete niche endpoint | Cleans up the temporary external analysis after extracting data |

### Data ingested

- Opportunity evaluation
- Competitor benchmarks
- Median review count
- Keyword opportunities
- Launch keyword count
- Competition strength indicators
- Seller/fulfilment signals where available

### Role in the pipeline

Tier 1.5 is **enrichment only**. It can confirm, challenge, or add nuance to Tier 1, but it does not automatically approve or kill ideas.

---

## Tier 2 — Reviews and Deep Research

Tier 2 begins only when a human moves an idea to `shortlisted`.

This human action is important because Tier 2 is significantly more expensive than Tier 1.

### Tier 2A — Review scraping

#### API points used

| API / parser | Purpose |
|---|---|
| Amazon review parser via scraping API | Scrapes review pages for selected competitor products |
| Amazon product-detail parser via scraping API | Fetches product details for the reviewed products |
| Optional keyword SERP fallback | Finds competitor products if Tier 1 evidence lacks product identifiers |

#### Typical process

```text
Task status becomes Shortlisted
  ↓
Review scraper job detects eligible idea
  ↓
Read competitor products from Tier 1 evidence
  ↓
Scrape review pages for top competitors
  ↓
Scrape product details
  ↓
Save reviews and product data to local idea memory
  ↓
Mark reviews_scraped = true
```

#### Data ingested

- Review text
- Star ratings
- Review pages
- Competitor product details
- Recurring complaints
- Use cases
- Feature requests
- Buyer objections

---

### Tier 2B — AI Deep Research

#### API / access point used

| Access point | Purpose |
|---|---|
| AI deep research tool via browser/API automation | Produces broader market research report for the idea |
| Task board API | Posts key findings back to the product discovery task |
| Local file storage | Saves full Markdown research report |

#### Typical process

```text
Task status becomes Shortlisted
  ↓
Research job detects eligible idea
  ↓
Prompt is built from concept + evidence
  ↓
Deep research session runs
  ↓
Report is extracted
  ↓
Quality checks run
  ↓
Markdown report is saved
  ↓
Key findings are posted to task board
  ↓
Mark research_done = true
```

#### Data ingested

- Market context
- Competitor positioning
- Customer segment assumptions
- Trend signals
- Risks
- Differentiation angles
- Strategic recommendation

---

### Tier 2C — Enhanced NPD analysis

This runs only when both review scraping and AI deep research are complete.

Inputs:

- Tier 1 scoring output
- Marketplace evidence
- Brand Analytics demand data
- Review corpus
- Deep research report
- Any Tier 1.5 enrichment

Outputs:

- Voice-of-customer summary
- Pain points
- Dealbreakers
- Usage scenarios
- Buyer motivations
- End-user avatar
- Buyer avatar
- Feature-response blueprint
- Differentiation strategy
- Recommendation

The system then marks Tier 2 complete and moves the task into the next review stage.

---

## Tier 3 — Pre-Sourcing Validation

Tier 3 begins only when a human moves the idea to `pre-sourcing`.

### API / model points used

| Tool/API | Purpose |
|---|---|
| Local idea memory | Loads all prior evidence and workflow state |
| LLM runtime | Generates product concept, buyer poll, listing draft, and sourcing spec |
| Task board API | Posts outputs and attaches structured payloads |
| Local file storage | Saves Tier 3 payloads for audit/reuse |

### Typical process

```text
Task status becomes Pre-Sourcing
  ↓
Pre-sourcing job detects eligible idea
  ↓
Load Tier 1, Tier 1.5, Tier 2 evidence
  ↓
Generate product concept
  ↓
Run simulated buyer preference poll vs current market leader
  ↓
Revise and retest if needed
  ↓
Generate listing draft
  ↓
Generate image/creative brief
  ↓
Generate manufacturer sourcing spec
  ↓
Post results to task board
  ↓
Mark presourcing_done = true
```

### Outputs

- Buyer poll result
- Product concept
- Listing title
- Bullet points
- Tagline
- Image shot list
- Materials spec
- Dimensions assumptions
- Packaging notes
- Compliance/safety notes
- Quote-volume assumptions
- Supplier search terms
- Lead-time assumptions

Tier 3 does not auto-approve. Human approval is still required before sourcing begins.

---

## Ingestion Cadence

| Cadence | Jobs / data | Why |
|---|---|---|
| Event-driven | Human task status changes, manually added ideas, approvals, dismissals | Human decisions control workflow progression |
| 3× daily | Autonomous product discovery scans | Keeps the idea pipeline populated without manual seeding |
| Daily | Human-seeded idea scoring, board sync, Tier 2 completion checks, digest/KPI reporting | Keeps the board current and processes ready analysis |
| Every few hours | Review scraping, deep research, external enrichment, pre-sourcing jobs | Moves human-approved ideas through deeper stages without manual job execution |
| Weekly | Brand Analytics search-term index, adjacency mining, large report ingestion | Large source reports are expensive/heavy and do not need per-idea ingestion |

---

## Systems of Record

| System | Role |
|---|---|
| Task board | Human-facing source of truth for idea status and decisions |
| Local idea memory | Automation source of truth for flags, cooldowns, budget, and completion state |
| Local search database | Queryable Brand Analytics search-demand source |
| Raw report files | Audit trail for generated research and analysis |
| Usage logs | Tracks external API and credit usage |

---

## Guardrails

- Do not run expensive scraping unless the idea has passed cheaper gates.
- Do not skip Brand Analytics/search-demand validation before scoring.
- Do not rely on an LLM to invent factual market data.
- Do not submit low-score ideas to the product board.
- Do not override human approvals or dismissals.
- Do not manually duplicate review scraping; it is expensive and state-gated.
- Keep raw data, scores, and recommendations separately auditable.

---

## Technical Pattern

The NPD system follows a layered pattern:

```text
External APIs + marketplace scraping
  ↓
Local indexing and structured storage
  ↓
Deterministic scoring and gating
  ↓
Human workflow board
  ↓
Expensive enrichment only after shortlist
  ↓
LLM synthesis over collected evidence
  ↓
Human approval before sourcing
```

The key principle is that factual evidence is collected and stored before interpretation. LLMs help with synthesis, product framing, and customer insight, but the core market data comes from explicit source systems and API calls.
