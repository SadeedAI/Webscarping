"""Orchestration: build queries, page through results. Knows nothing about proxies."""
import logging
from urllib.parse import quote

from .config import Config
from .parser import API_FIELDS, parse_page

log = logging.getLogger("bestbuy.extract")
MAX_PAGE_SIZE = 100   # documented maximum


def products_url(base_url: str, query: str) -> str:
    """e.g. query='search=laptop' -> {base}/products(search=laptop). No key in the URL."""
    return f"{base_url}/products({quote(query, safe='=&|()<>!*')})"


def extract_products(transport, cfg: Config, query: str, max_records=50, page_size=25, max_pages=5):
    """Fetch pages until max_records, max_pages, or the last page. Returns (records, summary)."""
    key = cfg.require_key()
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    url = products_url(cfg.base_url, query)
    records, skipped, total, page = [], 0, None, 1
    while page <= max_pages and len(records) < max_records:
        params = {"apiKey": key, "format": "json", "show": ",".join(API_FIELDS),
                  "pageSize": page_size, "page": page}
        payload = transport.get_json(url, params)
        recs, meta = parse_page(payload)
        skipped += meta["skipped"]
        total = meta["total"]
        records.extend(recs)
        log.info("page %s/%s: %d records", page, meta["total_pages"], len(recs))
        if not recs or (meta["total_pages"] is not None and page >= meta["total_pages"]):
            break
        page += 1
    return records[:max_records], {"pages_fetched": page, "skipped_entries": skipped, "total_matches": total}
