from bs4 import BeautifulSoup
import re


def _clean_text(value):
    if value is None:
        return None
    return re.sub(r"\s+", " ", value).strip() or None


def _parse_price_text(text):
    if not text:
        return None

    cleaned = text.replace(",", "").replace("$", "")
    match = re.search(r"(\d+(?:\.\d{1,2})?)", cleaned)

    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def extract_title(soup):
    selectors = ["#productTitle", "h1#title span", "h1 span"]

    for selector in selectors:
        el = soup.select_one(selector)

        if el:
            title = _clean_text(el.get_text(" ", strip=True))
            if title:
                return title

    return None


def extract_price(soup):
    selectors = [
        "#corePriceDisplay_desktop_feature_div .a-offscreen",
        "#corePriceDisplay_mobile_feature_div .a-offscreen",
        "#price_inside_buybox",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "span.a-price span.a-offscreen",
        "span.a-price .a-offscreen",
    ]

    for selector in selectors:
        el = soup.select_one(selector)

        if el:
            price = _parse_price_text(el.get_text(" ", strip=True))
            if price is not None:
                return price

    text = soup.get_text(" ", strip=True)
    match = re.search(r"\$(\d{1,5}(?:,\d{3})*(?:\.\d{2})?)", text)

    if match:
        return _parse_price_text(match.group(1))

    return None


def extract_rating(soup):
    selectors = [
        "span[data-hook='rating-out-of-text']",
        ".a-icon-alt",
        "#averageCustomerReviews span.a-icon-alt",
    ]

    for selector in selectors:
        el = soup.select_one(selector)

        if el:
            text = _clean_text(el.get_text(" ", strip=True))
            if text:
                match = re.search(r"(\d+(?:\.\d+)?)", text)
                if match:
                    try:
                        return float(match.group(1))
                    except ValueError:
                        pass

    return None


def extract_review_count(soup):
    selectors = [
        "#acrCustomerReviewText",
        "a[href*='customerReviews'] span",
        "span[data-hook='total-review-count']",
    ]

    for selector in selectors:
        el = soup.select_one(selector)

        if el:
            text = _clean_text(el.get_text(" ", strip=True)).replace(",", "")
            if text:
                match = re.search(r"\d+", text)
                if match:
                    try:
                        return int(match.group(0))
                    except ValueError:
                        pass

    return None


def extract_bullet_points(soup):
    bullets = []

    for element in soup.select("#feature-bullets ul li span:not(.a-list-item)"):
        text = _clean_text(element.get_text(" ", strip=True))
        if text and text not in bullets:
            bullets.append(text)

    return bullets


def extract_main_image(soup):
    selectors = [
        "#landingImage",
        "#imgTagWrapperId img",
        "img[data-old-hires]",
    ]

    for selector in selectors:
        el = soup.select_one(selector)

        if el:
            return el.get("data-old-hires") or el.get("src") or el.get("data-a-dynamic-image")

    return None


def extract_asin(soup):
    selectors = [
        "input#ASIN",
        "input[name='ASIN']",
        "#detailBullets_feature_div li span span",
    ]

    for selector in selectors:
        el = soup.select_one(selector)
        if el and el.get("value"):
            return el.get("value")

    text = soup.get_text(" ", strip=True)
    match = re.search(r"ASIN\s*[:\s]+([A-Z0-9]{10})", text)
    if match:
        return match.group(1)

    return None


def _extract_key_value_rows(container):
    details = {}

    for row in container.select("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) >= 2:
            key = _clean_text(cells[0].get_text(" ", strip=True))
            value = _clean_text(cells[1].get_text(" ", strip=True))

            if key and value:
                details[key] = value

    return details


def extract_product_details(soup):
    details = {}

    tables = [
        "#productDetails_techSpec_section_1",
        "#productDetails_detailBullets_sections1",
        "#detailBullets_wrapper_feature_div",
        "#productDetails_detailBullets_sections2",
    ]

    for selector in tables:
        container = soup.select_one(selector)
        if container:
            details.update(_extract_key_value_rows(container))

    for item in soup.select("#detailBullets_feature_div li"):
        label = item.select_one("span.a-text-bold")
        value = item.select_one("span:not(.a-text-bold)")

        if label and value:
            key = _clean_text(label.get_text(" ", strip=True)).rstrip(":")
            val = _clean_text(value.get_text(" ", strip=True))
            if key and val:
                details.setdefault(key, val)

    return details


def extract_listing_metadata(soup):
    metadata = {}

    mapping = {
        "brand": ["#bylineInfo", "a#bylineInfo", "a[href*='/stores/']"],
        "availability": ["#availability span", "#outOfStock"],
        "seller": ["#merchant-info", "#tabular-buybox-truncate-1"],
        "best_seller_rank": ["#productDetails_detailBullets_sections1", "#detailBulletsWrapper_feature_div"],
    }

    for key, selectors in mapping.items():
        for selector in selectors:
            el = soup.select_one(selector)
            if el:
                value = _clean_text(el.get_text(" ", strip=True))
                if value:
                    metadata[key] = value
                    break

    return metadata


def parse_amazon_product(html):
    soup = BeautifulSoup(html, "lxml")

    title = extract_title(soup)
    price = extract_price(soup)
    rating = extract_rating(soup)
    review_count = extract_review_count(soup)
    asin = extract_asin(soup)
    bullet_points = extract_bullet_points(soup)
    listing_metadata = extract_listing_metadata(soup)
    product_details = extract_product_details(soup)

    return {
        "asin": asin,
        "title": title,
        "brand": listing_metadata.get("brand"),
        "price": price,
        "rating": rating,
        "review_count": review_count,
        "main_image_url": extract_main_image(soup),
        "bullet_points": bullet_points,
        "listing_metadata": listing_metadata,
        "product_details": product_details,
        "availability": listing_metadata.get("availability"),
    }