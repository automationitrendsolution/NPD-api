import re
from bs4 import BeautifulSoup


def _clean_text(value):
    if value is None:
        return None
    return re.sub(r"\s+", " ", value).strip() or None


def _parse_rating(text):
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _parse_helpful_votes(text):
    if not text:
        return 0
    cleaned = text.replace(",", "")
    match = re.search(r"(\d+)", cleaned)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return 0


def _extract_title(review_el):
    """Pull review title, skipping the hidden star-text span inside the link."""
    title_el = review_el.select_one("[data-hook='review-title']")
    if not title_el:
        return None
    for span in title_el.find_all("span"):
        text = _clean_text(span.get_text(" ", strip=True))
        if text and "out of" not in text.lower() and "stars" not in text.lower():
            return text
    return None


def parse_amazon_reviews(html):
    """
    Parse an Amazon product-reviews page.

    Returns a list of dicts:
        {
            "review_id":         str | None,
            "title":             str | None,
            "rating":            float | None,   # e.g. 4.0
            "date":              str | None,      # as Amazon displays it
            "text":              str | None,
            "verified_purchase": bool,
            "helpful_votes":     int,
        }

    Only reviews that have body text are included.
    """
    soup = BeautifulSoup(html, "lxml")
    reviews = []

    for review_el in soup.select("[data-hook='review']"):
        # Body text — skip if empty (ad/placeholder blocks)
        body_el = review_el.select_one("[data-hook='review-body'] span")
        text = _clean_text(body_el.get_text(" ", strip=True)) if body_el else None
        if not text:
            continue

        review_id = review_el.get("id")
        title = _extract_title(review_el)

        rating_el = (
            review_el.select_one("[data-hook='review-star-rating'] .a-icon-alt")
            or review_el.select_one("[data-hook='cmps-review-star-rating'] .a-icon-alt")
        )
        rating = _parse_rating(
            _clean_text(rating_el.get_text(" ", strip=True)) if rating_el else None
        )

        date_el = review_el.select_one("[data-hook='review-date']")
        date = _clean_text(date_el.get_text(" ", strip=True)) if date_el else None

        verified_el = review_el.select_one("[data-hook='avp-badge']")
        verified = verified_el is not None

        helpful_el = review_el.select_one("[data-hook='helpful-vote-statement']")
        helpful_votes = _parse_helpful_votes(
            _clean_text(helpful_el.get_text(" ", strip=True)) if helpful_el else None
        )

        reviews.append({
            "review_id":         review_id,
            "title":             title,
            "rating":            rating,
            "date":              date,
            "text":              text,
            "verified_purchase": verified,
            "helpful_votes":     helpful_votes,
        })

    return reviews


def has_next_page(html):
    """
    Return True if the reviews page has a clickable 'Next page' button.

    Amazon marks the next-page li as 'a-last' when active and
    'a-last a-disabled' when it is the final page.
    """
    soup = BeautifulSoup(html, "lxml")
    # Active next-page button: li.a-last that is NOT disabled and contains a link
    next_li = soup.select_one("li.a-last")
    if next_li and "a-disabled" not in next_li.get("class", []):
        return next_li.find("a") is not None
    return False
