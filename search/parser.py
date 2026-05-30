from bs4 import BeautifulSoup
import re


def extract_price(item):
    selectors = [
        ".a-price .a-offscreen",
        "span.a-price span.a-offscreen",
        ".a-price-range .a-offscreen"
    ]

    for selector in selectors:
        el = item.select_one(selector)

        if el:
            text = (
                el.get_text(strip=True)
                .replace("$", "")
                .replace(",", "")
            )

            try:
                return float(text)
            except:
                pass

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

        title_el = item.select_one(
            "h2 span"
        )

        if title_el:
            title = title_el.get_text(
                strip=True
            )

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

# from bs4 import BeautifulSoup
# import re


# def clean_number(value):
#     if not value:
#         return None

#     value = value.replace(",", "").strip()

#     try:
#         return int(value)
#     except:
#         return None


# def parse_amazon_results(html):

#     soup = BeautifulSoup(html, "lxml")

#     products = []

#     results = soup.select(
#         'div[data-component-type="s-search-result"]'
#     )

#     for position, item in enumerate(results, start=1):

#         asin = item.get("data-asin")

#         if not asin:
#             continue

#         # Title
#         title = None

#         title_el = item.select_one("h2 span")

#         if title_el:
#             title = title_el.get_text(strip=True)

#         # Product URL
#         product_url = None

#         link_el = item.select_one("h2 a")

#         if link_el:
#             href = link_el.get("href")

#             if href:
#                 product_url = (
#                     "https://www.amazon.com" + href
#                 )

#         # Image
#         image_url = None

#         img_el = item.select_one("img.s-image")

#         if img_el:
#             image_url = img_el.get("src")

#         # Price
#         price = None

#         whole = item.select_one(".a-price-whole")
#         fraction = item.select_one(".a-price-fraction")

#         if whole:

#             whole_text = whole.get_text(
#                 strip=True
#             ).replace(",", "")

#             fraction_text = (
#                 fraction.get_text(strip=True)
#                 if fraction
#                 else "00"
#             )

#             try:
#                 price = float(
#                     f"{whole_text}.{fraction_text}"
#                 )
#             except:
#                 price = None

#         # Rating
#         rating = None

#         rating_el = item.select_one(
#             "span.a-icon-alt"
#         )

#         if rating_el:

#             rating_text = rating_el.get_text(
#                 strip=True
#             )

#             match = re.search(
#                 r"(\d+(\.\d+)?)",
#                 rating_text
#             )

#             if match:
#                 rating = float(
#                     match.group(1)
#                 )

#         # Reviews
#         reviews = None

#         review_el = item.select_one(
#             "span[aria-label$='ratings']"
#         )

#         if review_el:
#             reviews = clean_number(
#                 review_el.get_text(strip=True)
#             )

#         # Fallback review selector
#         if not reviews:

#             review_el = item.select_one(
#                 "span.a-size-base.s-underline-text"
#             )

#             if review_el:
#                 reviews = clean_number(
#                     review_el.get_text(strip=True)
#                 )

#         # Sponsored
#         sponsored = False

#         sponsored_text = item.get_text(
#             " ",
#             strip=True
#         ).lower()

#         if "sponsored" in sponsored_text:
#             sponsored = True

#         # Prime
#         is_prime = False

#         prime_icon = item.select_one(
#             "i.a-icon-prime"
#         )

#         if prime_icon:
#             is_prime = True

#         # Brand (best effort)
#         brand = None

#         if title:
#             brand = title.split()[0]

#         products.append({
#             "position": position,
#             "asin": asin,
#             "title": title,
#             "brand": brand,
#             "price": price,
#             "rating": rating,
#             "reviews": reviews,
#             "sponsored": sponsored,
#             "prime": is_prime,
#             "product_url": product_url,
#             "image_url": image_url
#         })

#     return products