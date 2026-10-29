"""Orchestration: follow 'next' links up to limits. Knows nothing about proxies or HTTP details."""
import logging

from bestbuy_scraper.errors import ScraperError
from .parser import parse_listing

log = logging.getLogger("htmlscraper.extract")


def scrape_listing(transport, start_url, max_pages=2, max_records=100, parse=parse_listing):
    """Return (records, summary). On a stop error, records gathered so far are kept and the error is reported."""
    records, url, pages, error = [], start_url, 0, None
    seen = set()
    while url and pages < max_pages and len(records) < max_records and url not in seen:
        seen.add(url)
        try:
            html = transport.get_text(url)
            recs, nxt = parse(html, url)
        except ScraperError as e:
            error = f"{type(e).__name__}: {e}"
            log.error("stopped at %s: %s", url, error)
            break
        pages += 1
        records.extend(recs)
        log.info("page %d: %d records", pages, len(recs))
        url = nxt
    return records[:max_records], {"pages_fetched": pages, "stopped_with": error}
