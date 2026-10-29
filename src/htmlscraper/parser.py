"""Pure HTML parsing for webscraper.io's e-commerce test site (schema.org Product markup).
Only fields present in the HTML are returned; nothing is invented (the site has no brand/stock field)."""
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from bestbuy_scraper.errors import MalformedResponse

FIELDS = ["name", "price", "currency", "url", "description", "rating", "review_count", "category"]
_PRICE = re.compile(r"[\d,]+(?:\.\d+)?")


def _price(text: str) -> Optional[float]:
    m = _PRICE.search(text or "")
    return float(m.group().replace(",", "")) if m else None


def _category(page_url: str) -> Optional[str]:
    parts = [p for p in urlparse(page_url).path.split("/") if p]
    return parts[-1] if "static" in parts and parts[-1] not in ("static", "e-commerce") else None


def parse_listing(html: str, page_url: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Return (records, next_page_url). Raises MalformedResponse if the page has no product container
    and no 'no products' signal (likely a block page or a changed layout)."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card.thumbnail")
    if not cards and not soup.select_one("ul.pagination, div.row"):
        raise MalformedResponse("page does not look like a product listing")
    out = []
    cat = _category(page_url)
    for c in cards:
        a = c.select_one("a.title")
        if a is None:
            continue
        price_el = c.select_one('[itemprop="price"]')
        cur_el = c.select_one('[itemprop="priceCurrency"]')
        desc = c.select_one('[itemprop="description"]')
        rating = c.select_one("p[data-rating]")
        reviews = c.select_one('[itemprop="reviewCount"]')
        out.append({
            "name": a.get("title") or a.get_text(strip=True),
            "price": _price(price_el.get_text()) if price_el else None,
            "currency": cur_el.get("content") if cur_el else None,
            "url": urljoin(page_url, a["href"]),
            "description": desc.get_text(strip=True) if desc else None,
            "rating": int(rating["data-rating"]) if rating and rating.get("data-rating", "").isdigit() else None,
            "review_count": int(reviews.get_text(strip=True)) if reviews and reviews.get_text(strip=True).isdigit() else None,
            "category": cat,
        })
    nxt = soup.select_one('ul.pagination a[rel="next"]')
    if nxt is None:
        # fallback: the link after the active page item
        active = soup.select_one("ul.pagination li.active")
        sib = active.find_next_sibling("li") if active else None
        link = sib.find("a", href=True) if sib else None
        nxt = link if link and link["href"] not in ("#", "") else None
    return out, (urljoin(page_url, nxt["href"]) if nxt is not None else None)
