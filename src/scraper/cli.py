"""Scraper CLI: python -m scraper.cli --pages 3 --details"""
import argparse
import csv
import json
import logging
import os
import sys
import time
from typing import Optional

from .parser import parse_detail, parse_listing
from .transport import HttpTransport, Response, TransportError, proxies_from_env

log = logging.getLogger("scraper")
FIELDS = ["title", "price_gbp", "rating", "in_stock", "category", "url"]


def fetch(tp: HttpTransport, url: str, retries: int = 2) -> Optional[Response]:
    """GET with limited retries. 429 honours Retry-After; other errors are logged, not hidden."""
    for attempt in range(retries + 1):
        try:
            r = tp.get(url)
        except TransportError as e:
            log.error("%s (attempt %d)", e, attempt + 1)
            continue
        if r.status == 200:
            return r
        if r.status == 429:
            wait = min(float(r.headers.get("retry-after", 5)), 30)
            log.warning("429 rate limited on %s, waiting %.1fs", url, wait)
            time.sleep(wait)
            continue
        log.error("HTTP %d on %s (not retried)", r.status, url)
        return None
    log.error("giving up on %s", url)
    return None


def scrape(tp: HttpTransport, start_url: str, pages: int, details: bool) -> list:
    books, url = [], start_url
    for n in range(1, pages + 1):
        if not url:
            break
        r = fetch(tp, url)
        if r is None:
            break
        page_books, url = parse_listing(r.text, r.url)
        log.info("page %d: %d books", n, len(page_books))
        books.extend(page_books)
    if details:
        for b in books:
            r = fetch(tp, b["url"]) if b["url"] else None
            b["category"] = parse_detail(r.text)["category"] if r else None
    for b in books:
        b.setdefault("category", None)
    return books


def save(books: list, outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "books.json"), "w", encoding="utf-8") as f:
        json.dump(books, f, indent=2, ensure_ascii=False)
    with open(os.path.join(outdir, "books.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(books)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start-url", default=os.getenv("SCRAPER_START_URL", "https://books.toscrape.com/catalogue/page-1.html"))
    p.add_argument("--pages", type=int, default=3)
    p.add_argument("--details", action="store_true", help="also fetch each book page for its category")
    p.add_argument("--timeout", type=float, default=float(os.getenv("SCRAPER_TIMEOUT", "10")))
    p.add_argument("--delay", type=float, default=float(os.getenv("SCRAPER_DELAY", "1")))
    p.add_argument("--out", default="output")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    tp = HttpTransport(timeout=a.timeout, delay=a.delay, proxies=proxies_from_env())
    books = scrape(tp, a.start_url, a.pages, a.details)
    if not books:
        log.error("No data extracted. Nothing saved.")
        return 1
    save(books, a.out)
    log.info("Saved %d books to %s", len(books), a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
