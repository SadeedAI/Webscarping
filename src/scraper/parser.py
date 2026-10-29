"""Pure HTML parsing. No network code here."""
from typing import List, Optional, Tuple
from urllib.parse import urljoin
import re

from bs4 import BeautifulSoup

RATING = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


def _price(text: str) -> Optional[float]:
    m = re.search(r"\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else None


def parse_listing(html: str, base_url: str) -> Tuple[List[dict], Optional[str]]:
    """Return (books, next_page_url). Missing fields become None."""
    soup = BeautifulSoup(html, "html.parser")
    books = []
    for art in soup.select("article.product_pod"):
        a = art.select_one("h3 a")
        price = art.select_one("p.price_color")
        rating = art.select_one("p.star-rating")
        avail = art.select_one("p.availability")
        rating_word = next((c for c in (rating.get("class", []) if rating else []) if c in RATING), None)
        books.append({
            "title": a.get("title") if a else None,
            "price_gbp": _price(price.get_text()) if price else None,
            "rating": RATING.get(rating_word),
            "in_stock": ("in stock" in avail.get_text().lower()) if avail else None,
            "url": urljoin(base_url, a["href"]) if a and a.get("href") else None,
        })
    nxt = soup.select_one("li.next a")
    return books, (urljoin(base_url, nxt["href"]) if nxt and nxt.get("href") else None)


def parse_detail(html: str) -> dict:
    """Extract category from a book detail page."""
    soup = BeautifulSoup(html, "html.parser")
    crumbs = soup.select("ul.breadcrumb li a")
    return {"category": crumbs[2].get_text(strip=True) if len(crumbs) >= 3 else None}
