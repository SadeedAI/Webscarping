"""Site registry: the ONLY site-specific part of the project. The transport and proxy code are shared.

To add a site: write `parse(html, page_url) -> (records, next_url)`, list its FIELDS, and add an entry.
"""
from dataclasses import dataclass
from typing import Callable, List

from bs4 import BeautifulSoup

from bestbuy_scraper.errors import MalformedResponse
from . import parser as shop


def parse_countries(html: str, page_url: str):
    """scrapethissite.com /pages/simple/ : one HTML page with country cards. No pagination."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.country")
    if not cards:
        raise MalformedResponse("page has no country cards (block page or layout change)")
    out = []
    for c in cards:
        def txt(sel):
            el = c.select_one(sel)
            return el.get_text(strip=True) if el else None

        def num(sel):
            t = txt(sel)
            try:
                return float(t) if t is not None else None
            except ValueError:
                return None
        out.append({"name": txt("h3.country-name"), "capital": txt(".country-capital"),
                    "population": num(".country-population"), "area_km2": num(".country-area"),
                    "url": page_url})
    return out, None


@dataclass
class Site:
    name: str
    start_url: str
    parse: Callable
    fields: List[str]
    min_delay: float          # seconds between requests; never go below this
    rules_note: str


SITES = {
    "webscraper_ecommerce": Site(
        "webscraper_ecommerce", "https://webscraper.io/test-sites/e-commerce/static/computers/laptops",
        shop.parse_listing, shop.FIELDS, 1.0,
        "Practice shop. robots.txt allows this path. No stated rate limit."),
    "scrapethissite_countries": Site(
        "scrapethissite_countries", "https://www.scrapethissite.com/pages/simple/",
        parse_countries, ["name", "capital", "population", "area_km2", "url"], 1.5,
        "FAQ allows scraping; documents max 1 request/second, identifying User-Agent, robots.txt, "
        "and temporary/permanent bans. Not a shop."),
}
