from bs4 import BeautifulSoup
import re


def _parse_price_text(text):
    if not text:
        return None

    cleaned = text.replace(",", "")
    match = re.search(r"(\d+(?:\.\d{1,2})?)", cleaned)

    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def extract_price(item):
    selectors = [
        ".a-price .a-offscreen",
        "span.a-price span.a-offscreen",
        ".a-price-range .a-offscreen",
        "span.a-price[data-a-size='xl'] .a-offscreen",
        "span[aria-label*='$']"
    ]

    for selector in selectors:
        el = item.select_one(selector)

        if el:
            text = el.get_text(strip=True).replace("$", "")
            price = _parse_price_text(text)

            if price is not None:
                return price

    whole = item.select_one(".a-price-whole")
    fraction = item.select_one(".a-price-fraction")

    if whole:
        whole_text = whole.get_text(strip=True).replace(",", "")
        fraction_text = fraction.get_text(strip=True) if fraction else "00"
        price = _parse_price_text(f"{whole_text}.{fraction_text}")

        if price is not None:
            return price

    full_text = item.get_text(" ", strip=True)
    match = re.search(r"\$(\d{1,5}(?:,\d{3})*(?:\.\d{2})?)", full_text)

    if match:
        return _parse_price_text(match.group(1))

    return None


def extract_rating(item):
    selectors = [
        "span.a-icon-alt",
        "[aria-label*='out of 5 stars']"
    ]

    for selector in selectors:
        el = item.select_one(selector)

        if el:

            text = el.get_text(strip=True)

            match = re.search(
                r"(\d+(\.\d+)?)",
                text
            )

            if match:
                return float(match.group(1))

    return None


def extract_reviews(item):

    selectors = [
        "a[href*='customerReviews'] span",
        "span.a-size-base.s-underline-text",
        "span[aria-label*='ratings']"
    ]

    for selector in selectors:

        el = item.select_one(selector)

        if el:

            text = (
                el.get_text(strip=True)
                .replace(",", "")
            )

            match = re.search(
                r"\d+",
                text
            )

            if match:
                return int(match.group())

    return None


def extract_product_url(item):

    selectors = [
        "h2 a",
        "a.a-link-normal.s-line-clamp-2",
        "a.a-link-normal.s-no-outline"
    ]

    for selector in selectors:

        el = item.select_one(selector)

        if el:

            href = el.get("href")

            if href:

                if href.startswith("/"):
                    return (
                        "https://www.amazon.com"
                        + href
                    )

                return href

    return None


def extract_image(item):

    selectors = [
        "img.s-image",
        "img[data-image-latency='s-product-image']"
    ]

    for selector in selectors:

        el = item.select_one(selector)

        if el:
            return (
                el.get("src")
                or el.get("data-src")
            )

    return None


def extract_prime(item):

    selectors = [
        "i.a-icon-prime",
        ".a-icon-prime",
        "[aria-label='Amazon Prime']"
    ]

    for selector in selectors:

        if item.select_one(selector):
            return True

    return False


def extract_coupon(item):

    text = item.get_text(
        " ",
        strip=True
    )

    patterns = [
        r"Save\s+\d+%",
        r"\d+%\s+off",
        r"Coupon"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:
            return match.group()

    return None


def parse_amazon_results(html):

    soup = BeautifulSoup(
        html,
        "lxml"
    )

    products = []

    results = soup.select(
        'div[data-component-type="s-search-result"]'
    )

    for position, item in enumerate(
        results,
        start=1
    ):

        asin = item.get("data-asin")

        if not asin:
            continue

        title = None

        title_el = item.select_one("h2 span") or item.select_one("h2")

        if title_el:
            title = title_el.get_text(strip=True)

        full_text = item.get_text(
            " ",
            strip=True
        ).lower()

        products.append({
            "position": position,
            "asin": asin,
            "title": title,
            "brand": (
                title.split()[0]
                if title else None
            ),
            "price": extract_price(item),
            "rating": extract_rating(item),
            "reviews": extract_reviews(item),
            "sponsored": (
                "sponsored" in full_text
            ),
            "prime": extract_prime(item),
            "amazon_choice": (
                "amazon's choice"
                in full_text
            ),
            "best_seller": (
                "best seller"
                in full_text
            ),
            "coupon": extract_coupon(item),
            "delivery": (
                "delivery"
                if "delivery" in full_text
                else None
            ),
            "product_url": extract_product_url(item),
            "image_url": extract_image(item)
        })

    return products