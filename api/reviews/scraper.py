import os
import time
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

_MAX_RETRIES = 3
_RETRY_DELAYS = [5, 15, 30]  # seconds between retries


def fetch_amazon_reviews(asin, page=1):
    """
    Fetch one page of Amazon customer reviews for an ASIN via ScrapingBee.

    Uses JS rendering + US premium residential proxy so Amazon's full review
    page loads and anti-bot checks are bypassed. Retries up to 3 times on
    transient 500 errors before raising.

    Returns raw HTML string.
    """
    asin = asin.strip().upper()
    if not asin:
        raise ValueError("asin is required")

    if not SCRAPINGBEE_API_KEY:
        raise ValueError("SCRAPINGBEE_API_KEY environment variable is required")

    url = (
        f"https://www.amazon.com/product-reviews/{asin}"
        f"?pageNumber={page}"
        f"&reviewerType=all_reviews"
        f"&filterByStar=all_stars"
        f"&sortBy=recent"
    )

    last_error = None
    for attempt in range(_MAX_RETRIES):
        if attempt > 0:
            time.sleep(_RETRY_DELAYS[attempt - 1])

        try:
            response = requests.get(
                "https://app.scrapingbee.com/api/v1/",
                params={
                    "api_key":        SCRAPINGBEE_API_KEY,
                    "url":            url,
                    "render_js":      "true",
                    "premium_proxy":  "true",
                    "country_code":   "us",
                    "wait":           "2000",
                    "block_resources": "false",
                },
                timeout=120,
            )
        except requests.exceptions.Timeout:
            last_error = f"Request timed out (attempt {attempt + 1})"
            continue
        except requests.exceptions.RequestException as exc:
            last_error = f"Network error (attempt {attempt + 1}): {exc}"
            continue

        if response.status_code == 500:
            last_error = f"ScrapingBee 500 (attempt {attempt + 1}): {response.text[:200]}"
            continue  # retry on transient ScrapingBee error

        if not response.ok:
            raise RuntimeError(
                f"ScrapingBee {response.status_code}: {response.text[:300]}"
            )

        return response.text

    raise RuntimeError(
        f"ScrapingBee failed after {_MAX_RETRIES} attempts for ASIN {asin}. "
        f"Last error: {last_error}"
    )
