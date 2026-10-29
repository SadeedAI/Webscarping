"""python -m htmlscraper.cli --max-pages 2 --out output/live"""
import argparse
import logging
import sys

from bestbuy_scraper.config import _num, load_dotenv
from bestbuy_scraper.errors import ConfigError
from .extractor import scrape_listing
import os

from .proxy_iface import provider_from_env
from .sites import SITES
from .transport import HtmlTransport
from .writer import write_products, write_request_log


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HTML product scraper (webscraper.io e-commerce test site).")
    ap.add_argument("--site", default="webscraper_ecommerce", choices=sorted(SITES))
    ap.add_argument("--start-url", default=None, help="override the site's default start URL")
    ap.add_argument("--max-pages", type=int, default=2)
    ap.add_argument("--max-records", type=int, default=50)
    ap.add_argument("--out", default="output/live")
    ap.add_argument("--failover", action="store_true",
                    help="after a 403/429 let the proxy provider rotate route (bounded). Off by default.")
    ap.add_argument("--label", default="LIVE", help="data_origin tag written to products.json")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()
    try:
        env = os.environ
        provider = provider_from_env(env)
        timeout = _num(env, "SCRAPER_TIMEOUT", 15.0, 1, 120)
        delay = _num(env, "SCRAPER_DELAY", 2.0, 1, 60)
    except ConfigError as e:
        print(f"CONFIG ERROR: {e}", file=sys.stderr)
        return 2
    site = SITES[a.site]
    start_url = a.start_url or site.start_url
    delay = max(delay, site.min_delay)          # never faster than the site's documented pace
    tr = HtmlTransport(provider, timeout=timeout, delay=delay, failover=a.failover)
    recs, summary = scrape_listing(tr, start_url, a.max_pages, a.max_records, site.parse)
    summary["proxy_provider"] = provider.describe()
    summary["site"] = site.name
    write_request_log(tr.events, os.path.join(a.out, "request_log.csv"))
    if recs:
        c, j = write_products(recs, a.out, start_url, summary, a.label, site.fields)
        print(f"Saved {len(recs)} records -> {c} , {j}")
    else:
        print(f"No records. {summary}")
    return 0 if recs and not summary["stopped_with"] else 1


if __name__ == "__main__":
    sys.exit(main())
