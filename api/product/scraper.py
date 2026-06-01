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


def _build_amazon_product_url(product_url=None, asin=None):
    if product_url:
        return product_url

    if asin:
        asin = asin.strip().upper()

        if not asin:
            raise ValueError("asin is required")

        return f"https://www.amazon.com/dp/{asin}"

    raise ValueError("asin or product_url is required")


def fetch_amazon_product(product_url=None, asin=None):
    product_url = _build_amazon_product_url(product_url=product_url, asin=asin)

    if not SCRAPINGBEE_API_KEY:
        raise ValueError("SCRAPINGBEE_API_KEY environment variable is required")

    response = requests.get(
        "https://app.scrapingbee.com/api/v1/",
        params={
            "api_key": SCRAPINGBEE_API_KEY,
            "url": product_url,
            "render_js": "true",
            "premium_proxy": "true",
            "country_code": "us",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.text