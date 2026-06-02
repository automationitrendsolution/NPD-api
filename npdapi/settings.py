import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-fk5@q)l@phw#rh5b39ki=g#m_y$)i_ao_^h87&@y*nsm1p7-_2'

DEBUG = True

ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# ── Apps ──────────────────────────────────────────────────────────────────────
# admin / auth / contenttypes / sessions removed — no SQL database in this project.
# All persistent data lives in MongoDB (ideas collection, ba_search_terms, etc.).
INSTALLED_APPS = [
    'django.contrib.staticfiles',
    'rest_framework',
    'api',
    'frontend',
]

# ── Middleware ────────────────────────────────────────────────────────────────
# SessionMiddleware and AuthenticationMiddleware removed (no SQL backend).
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'npdapi.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
            ],
        },
    },
]

WSGI_APPLICATION = 'npdapi.wsgi.application'

# ── No SQL database ───────────────────────────────────────────────────────────
# All data is stored in MongoDB. Django's ORM is not used.
DATABASES = {}

# ── Django REST Framework ─────────────────────────────────────────────────────
# Disable default auth/permission classes — they require contenttypes/auth apps.
# This API has no login; all endpoints are open (protected by network/firewall).
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': [],
    'UNAUTHENTICATED_USER': None,
}

# ── MongoDB ───────────────────────────────────────────────────────────────────
# Primary (and only) database for this project.
# Local dev: mongodb://localhost:27017/npd_db  (no auth)
# Docker:    docker-compose.yml overrides MONGO_URI with authenticated URI.
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/npd_db")
MONGO_DB  = os.getenv("MONGO_DB",  "npd_db")

# ── NPD Idea Memory ───────────────────────────────────────────────────────────
# Kept for backward compatibility — IdeaMemoryStore ignores this path.
IDEA_MEMORY_PATH = BASE_DIR / 'data' / 'ideas.ndjson'

# ── Brand Analytics ───────────────────────────────────────────────────────────
# Kept for backward compatibility — db.py functions ignore this path.
BA_DB_PATH = BASE_DIR / 'data' / 'brand_analytics.sqlite3'

# ── Internationalisation ──────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ── Static files ──────────────────────────────────────────────────────────────
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
