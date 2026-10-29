"""Command line entry. Run: python -m bestbuy_scraper.cli --query "search=laptop" --max-records 25"""
import argparse
import logging
import sys

from .config import Config, load_dotenv
from .errors import ConfigError, ScraperError
from .extractor import extract_products
from .transport import HttpTransport
from .writer import write_outputs, write_request_log


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fetch products from the official Best Buy API.")
    ap.add_argument("--query", default="search=laptop", help="Products API filter, e.g. search=laptop")
    ap.add_argument("--max-records", type=int, default=25)
    ap.add_argument("--page-size", type=int, default=25)
    ap.add_argument("--max-pages", type=int, default=3)
    ap.add_argument("--out", default="output")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()
    try:
        cfg = Config.from_env()
        cfg.require_key()
    except ConfigError as e:
        print(f"CONFIG ERROR: {e}", file=sys.stderr)
        return 2
    tr = HttpTransport(cfg.timeout, cfg.delay, cfg.proxies, cfg.max_retries, cfg.max_retry_wait)
    code = 0
    records, summary = [], {}
    try:
        records, summary = extract_products(tr, cfg, a.query, a.max_records, a.page_size, a.max_pages)
    except ScraperError as e:
        print(f"STOPPED: {type(e).__name__}: {e}", file=sys.stderr)
        code = 1
    write_request_log(tr.events, f"{a.out}/bestbuy_request_log.csv")
    if records:
        c, j = write_outputs(records, a.out, a.query, summary)
        print(f"Saved {len(records)} records -> {c} and {j}")
    elif code == 0:
        print("No records returned.")
        code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
