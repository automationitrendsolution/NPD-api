import json
import os
from pathlib import Path

import requests


def _load_dotenv():
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY")


def fetch_amazon_reviews(asin, page=1):
    """
    Fetch one page of Amazon customer reviews for an ASIN.

    Uses ScrapingBee with JS rendering and a US premium proxy so the
    review content loads in full and anti-bot checks are bypassed.

    Returns raw HTML string.
    """
    asin = asin.strip().upper()
    if not asin:
        raise ValueError("asin is required")

    if not SCRAPINGBEE_API_KEY:
        raise ValueError("SCRAPINGBEE_API_KEY environment variable is required")

    # Amazon review pages are server-side rendered (reviews in initial HTML),
    # so render_js=false avoids the headless-browser fingerprint that triggers
    # bot detection. premium_proxy still rotates IPs for anonymity.
    url = (
        f"https://www.amazon.com/product-reviews/{asin}"
        f"?pageNumber={page}"
        f"&sortBy=recent"
        f"&reviewerType=all_reviews"
        f"&filterByStar=all_stars"
    )

    response = requests.get(
        "https://app.scrapingbee.com/api/v1/",
        params={
            "api_key":       SCRAPINGBEE_API_KEY,
            "url":           url,
            "render_js":     "false",
            "premium_proxy": "true",
            "country_code":  "us",
        },
        timeout=90,
    )

    if not response.ok:
        raise RuntimeError(
            f"ScrapingBee {response.status_code}: {response.text[:300]}"
        )
    return response.text
