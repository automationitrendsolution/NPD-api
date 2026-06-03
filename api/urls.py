from django.urls import path
from . import views

app_name = 'api'
urlpatterns = [
    # ── Amazon scraping ───────────────────────────────────────────────────────
    path("amazon-search/",  views.amazon_search,         name="amazon-search"),
    path("amazon-product/", views.amazon_product_detail, name="amazon-product"),

    # ── Idea memory ───────────────────────────────────────────────────────────
    # POST   /api/ideas/              → create a new idea
    # GET    /api/ideas/              → list ideas (with optional query filters)
    # GET    /api/ideas/<idea_id>/    → get one idea by ID
    # PATCH  /api/ideas/<idea_id>/update/  → update fields on one idea
    path("ideas/",                      views.idea_list,   name="idea-list"),
    path("ideas/create/",               views.idea_create, name="idea-create"),
    path("ideas/<str:idea_id>/",        views.idea_detail, name="idea-detail"),
    path("ideas/<str:idea_id>/update/", views.idea_update, name="idea-update"),
    path("ideas/<str:idea_id>/delete/", views.idea_delete, name="idea-delete"),

    # ── Brand Analytics ───────────────────────────────────────────────────────
    # GET  /api/brand-analytics/lookup/?keyword=bamboo+mug        → single lookup
    # GET  /api/brand-analytics/lookup-batch/?keywords=a,b,c      → batch lookup
    # GET  /api/brand-analytics/status/                           → DB health check
    path("brand-analytics/lookup/",       views.ba_lookup,        name="ba-lookup"),
    path("brand-analytics/lookup-batch/", views.ba_lookup_batch,  name="ba-lookup-batch"),
    path("brand-analytics/status/",       views.ba_status,        name="ba-status"),
    path("brand-analytics/ingest/",       views.ba_ingest,        name="ba-ingest"),

    # ── Tier 1 scoring ────────────────────────────────────────────────────────
    # POST /api/score/  → run full Tier 1 pipeline for a keyword or idea_id
    path("score/", views.score_idea_view, name="score-idea"),

    # ── LLM analysis (Tier 2C + Tier 3) ──────────────────────────────────────
    # POST /api/analyse/   → Tier 2C: GPT-4o synthesis of all evidence
    # POST /api/presource/ → Tier 3: GPT-4o-mini pre-sourcing doc generation
    path("analyse/",    views.analyse_idea,   name="analyse-idea"),
    path("presource/",  views.presource_idea, name="presource-idea"),

    # ── Tier 2A — Review scraping ─────────────────────────────────────────────
    # POST /api/reviews/scrape/ → scrape Amazon reviews for a shortlisted idea
    path("reviews/scrape/", views.scrape_reviews_view, name="scrape-reviews"),

    # ── System health ──────────────────────────────────────────────────────────
    # GET /api/db-status/ → MongoDB connectivity + collection stats
    path("db-status/", views.db_status, name="db-status"),

    # ── Research History ───────────────────────────────────────────────────────
    # GET/POST /api/research-history/                    → list or save
    # DELETE   /api/research-history/clear/              → wipe all
    # DELETE   /api/research-history/<history_id>/       → delete one
    path("research-history/",                    views.research_history,        name="research-history"),
    path("research-history/clear/",              views.research_history_clear,  name="research-history-clear"),
    path("research-history/<str:history_id>/",   views.research_history_delete, name="research-history-delete"),
]
