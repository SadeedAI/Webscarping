"""SIMULATED rate-limit demo. Talks ONLY to a local fake server, never to Best Buy.

Run: python -m bestbuy_scraper.ratelimit_demo
Writes output/SIMULATED_ratelimit_log.csv
"""
import sys

from .errors import ScraperError
from .sim_server import start_in_thread
from .transport import HttpTransport
from .writer import write_request_log


def main(out="output/SIMULATED_ratelimit_log.csv"):
    # Scenario A: 429 with Retry-After (generic API style). Scenario B: 403 quota (Best Buy documented style).
    events = []
    for over in ("429", "403"):
        srv, base = start_in_thread(limit=3, over=over, retry_after=1)
        tr = HttpTransport(delay=0.25, max_retries=2)
        url = base + "/v1/products(search=x)"
        try:
            for _ in range(6):
                tr.get_json(url, {"apiKey": "DEMO"})
        except ScraperError as e:
            print(f"[{over}] stopped with {type(e).__name__}: {e}")
        events.extend(tr.events)
        srv.shutdown()
    write_request_log(events, out)
    print(f"SIMULATED log written: {out}")


if __name__ == "__main__":
    sys.exit(main())
