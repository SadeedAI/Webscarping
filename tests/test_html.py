"""Tests for htmlscraper. Labels: UNIT (real captured HTML fixture), SIMULATED (local fake site),
PROXY-IFACE (local stub proxies). None of these contact a real website or a real proxy."""
import csv
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from bestbuy_scraper import errors as E
from htmlscraper.extractor import scrape_listing
from htmlscraper.parser import FIELDS, parse_listing
from htmlscraper.proxy_iface import NoProxy, ProxyPool, StaticProxy, provider_from_env
from htmlscraper.sim_site import FIXTURE, PATH, start
from htmlscraper.transport import HtmlTransport, parse_retry_after, redact
from htmlscraper.writer import write_products, write_request_log

REAL_URL = "https://webscraper.io" + PATH
HTML = open(FIXTURE, encoding="utf-8").read()


def tr(provider=None, **kw):
    kw.setdefault("delay", 0)
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("jitter", False)
    return HtmlTransport(provider, **kw)


# ---------------- UNIT: parser on REAL captured HTML ----------------
def test_parse_real_page():
    recs, nxt = parse_listing(HTML, REAL_URL)
    assert len(recs) == 6
    r = recs[0]
    assert r["name"] == "Packard 255 G2" and r["price"] == 416.99 and r["currency"] == "USD"
    assert r["url"] == "https://webscraper.io/test-sites/e-commerce/static/product/31"
    assert r["rating"] == 2 and r["review_count"] == 2 and r["category"] == "laptops"
    assert nxt == REAL_URL + "?page=2"
    assert set(r) == set(FIELDS)


def test_parse_rejects_block_page():
    from bestbuy_scraper.errors import MalformedResponse
    with pytest.raises(MalformedResponse):
        parse_listing("<html><body>Access denied</body></html>", REAL_URL)


def test_parse_missing_price_is_none():
    html = HTML.replace('<span itemprop="price">$416.99</span>', "")
    recs, _ = parse_listing(html, REAL_URL)
    assert recs[0]["price"] is None


def test_writer(tmp_path):
    recs, _ = parse_listing(HTML, REAL_URL)
    c, j = write_products(recs, str(tmp_path), REAL_URL, {}, "FIXTURE")
    assert len(list(csv.DictReader(open(c, encoding="utf-8")))) == 6
    assert json.load(open(j, encoding="utf-8"))["data_origin"] == "FIXTURE"


# ---------------- UNIT: helpers ----------------
def test_retry_after_parsing():
    assert parse_retry_after("7") == 7
    assert parse_retry_after(None) is None
    assert parse_retry_after("junk") is None
    assert parse_retry_after("Wed, 21 Oct 2026 07:28:10 GMT", now=1792567670 - 5) is not None


def test_redact_proxy_credentials():
    assert "secretpw" not in redact("http://user:secretpw@host:8080")


# ---------------- SIMULATED: happy path + robots ----------------
def test_sim_scrape_ok():
    srv, base = start()
    t = tr()
    recs, summ = scrape_listing(t, base + PATH, max_pages=1)
    assert len(recs) == 6 and summ["stopped_with"] is None
    assert srv.state["log"][0] == "/robots.txt"       # robots checked first
    srv.shutdown()


def test_sim_robots_disallow_blocks_fetch():
    srv, base = start(robots="User-agent: *\nDisallow: /test-sites/\n")
    t = tr()
    recs, summ = scrape_listing(t, base + PATH)
    assert recs == [] and "ForbiddenError" in summ["stopped_with"]
    assert PATH not in " ".join(srv.state["log"])      # page never requested
    srv.shutdown()


# ---------------- SIMULATED: error handling ----------------
def test_sim_429_retry_after_honoured_then_bounded():
    srv, base = start(mode="429", limit=0, retry_after=3)
    sleeps = []
    t = tr(sleep=sleeps.append, max_retries=2)
    with pytest.raises(E.RateLimitError):
        t.get_text(base + PATH)
    page_hits = [e for e in t.events if e["status"] == 429]
    assert len(page_hits) == 3                         # 1 try + 2 retries then stop
    assert sleeps.count(3.0) == 2                      # waited exactly Retry-After
    srv.shutdown()


def test_sim_429_without_retry_after_stops():
    srv, base = start(mode="429", limit=0, retry_after="x")
    t = tr()
    with pytest.raises(E.RateLimitError):
        t.get_text(base + PATH)
    assert len([e for e in t.events if e["status"] == 429]) == 1
    srv.shutdown()


def test_sim_403_never_retried():
    srv, base = start(mode="403", limit=0)
    t = tr()
    with pytest.raises(E.ForbiddenError):
        t.get_text(base + PATH)
    assert len([e for e in t.events if e["status"] == 403]) == 1
    srv.shutdown()


def test_sim_500_exponential_backoff():
    srv, base = start()
    sleeps = []
    t = tr(sleep=sleeps.append, max_retries=3, backoff_base=2.0, respect_robots=False)
    with pytest.raises(E.ServerError):
        t._request(base + "/boom")
    waits = [s for s in sleeps if s > 0]
    assert waits == [2.0, 4.0, 8.0]                    # 2 * 2^attempt
    srv.shutdown()


def test_timeout_and_connection_refused():
    with pytest.raises(E.TransportError):
        tr(max_retries=1, timeout=1, respect_robots=False)._request("http://127.0.0.1:9/x")


def test_partial_results_kept_when_blocked_midway():
    srv, base = start(mode="403", limit=1)             # page 1 ok; its 'next' link 403s
    recs, summ = scrape_listing(tr(), base + PATH, max_pages=3)
    assert len(recs) == 6 and "ForbiddenError" in summ["stopped_with"]
    srv.shutdown()


# ---------------- PROXY-IFACE ----------------
class StubProxy:
    """Local forward-proxy stand-in. mode: 'ok' serves the page, '403' blocks."""

    def __init__(self, mode):
        self.seen = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.seen.append(self.path)
                if "robots.txt" in self.path:
                    body, code = b"User-agent: *\nDisallow:\n", 200
                elif mode == "ok":
                    body, code = HTML.encode(), 200
                elif mode == "407":
                    body, code = b"proxy auth required", 407
                else:
                    body, code = b"blocked", 403
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"


def test_proxy_used_for_requests():
    p = StubProxy("ok")
    t = tr(StaticProxy(p.url))
    recs, _ = scrape_listing(t, "http://shop.example.invalid" + PATH, max_pages=1)
    assert len(recs) == 6 and p.seen and p.seen[-1].startswith("http://shop.example.invalid")
    p.srv.shutdown()


def test_failover_rotates_to_working_proxy():
    bad, good = StubProxy("403"), StubProxy("ok")
    pool = ProxyPool([bad.url, good.url])
    t = tr(pool, failover=True)
    # robots.txt is served by both; the page is blocked by `bad`, then retried through `good`
    recs, summ = scrape_listing(t, "http://shop.example.invalid" + PATH, max_pages=1)
    assert len(recs) == 6 and summ["stopped_with"] is None
    assert [e["status"] for e in t.events if PATH in e["url"]] == [403, 200]
    bad.srv.shutdown(); good.srv.shutdown()


def test_failover_off_by_default_stops():
    bad, good = StubProxy("403"), StubProxy("ok")
    t = tr(ProxyPool([bad.url, good.url]))
    recs, summ = scrape_listing(t, "http://shop.example.invalid" + PATH, max_pages=1)
    assert recs == [] and "ForbiddenError" in summ["stopped_with"]
    assert not good.seen
    bad.srv.shutdown(); good.srv.shutdown()


def test_failover_gives_up_when_all_proxies_blocked():
    a, b = StubProxy("403"), StubProxy("403")
    t = tr(ProxyPool([a.url, b.url]), failover=True, max_failovers=5)
    recs, summ = scrape_listing(t, "http://shop.example.invalid" + PATH, max_pages=1)
    assert recs == [] and summ["stopped_with"]
    assert len([e for e in t.events if e["status"] == 403 and PATH in e["url"]]) == 2   # each tried once
    a.srv.shutdown(); b.srv.shutdown()


def test_failover_needs_rotating_provider():
    t = tr(NoProxy(), failover=True)
    srv, base = start(mode="403", limit=0)
    with pytest.raises(E.ForbiddenError):
        t.get_text(base + PATH)
    assert len([e for e in t.events if e["status"] == 403]) == 1
    srv.shutdown()


def test_provider_from_env():
    assert isinstance(provider_from_env({}), NoProxy)
    assert isinstance(provider_from_env({"SCRAPER_HTTP_PROXY": "http://h:1"}), StaticProxy)
    assert isinstance(provider_from_env({"SCRAPER_PROXY_LIST": "http://a:1, http://b:2"}), ProxyPool)
    with pytest.raises(E.ConfigError):
        provider_from_env({"SCRAPER_PROXY_LIST": "http://a:1,notaproxy"})


def test_pool_cooldown():
    now = [0]
    pool = ProxyPool(["http://a:1", "http://b:2"], cooldown=100, clock=lambda: now[0])
    pool.report_blocked("http://a:1", 403)
    assert pool.rotate() and pool.current() == "http://b:2"
    pool.report_blocked("http://b:2", 403)
    assert pool.rotate() is False                      # a still resting
    now[0] = 101
    assert pool.rotate() and pool.current() == "http://a:1"


def test_request_log_hides_proxy_credentials(tmp_path):
    srv, base = start()
    t = tr(StaticProxy("http://u:pw123@127.0.0.1:9"), max_retries=0)
    scrape_listing(t, base + PATH, max_pages=1)
    p = tmp_path / "l.csv"
    write_request_log(t.events, str(p))
    assert "pw123" not in p.read_text()
    srv.shutdown()
