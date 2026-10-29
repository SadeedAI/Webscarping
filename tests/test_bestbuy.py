"""Tests for the Best Buy client. Labels: UNIT, MOCKED, SIMULATED (local fake server).
NONE of these tests contact Best Buy. They prove the client's behaviour, not Best Buy's."""
import csv
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from bestbuy_scraper import errors as E
from bestbuy_scraper.config import Config, proxies_from_env
from bestbuy_scraper.extractor import extract_products, products_url
from bestbuy_scraper.parser import RECORD_FIELDS, parse_page, parse_product
from bestbuy_scraper.sim_server import fake_product, start_in_thread
from bestbuy_scraper.transport import HttpTransport, classify_403, redact
from bestbuy_scraper.writer import write_outputs, write_request_log

KEY = "SECRETKEY123"


def fast(**kw):
    kw.setdefault("delay", 0)
    kw.setdefault("sleep", lambda s: None)
    return HttpTransport(**kw)


def cfg(base):
    return Config(api_key=KEY, base_url=base + "/v1", delay=0)


# ---------- UNIT: parsing ----------
def test_parse_full_product():
    r = parse_product(fake_product(1))
    assert r["product_id"] == 1001 and r["brand"] == "FixtureBrand"
    assert r["category"] == "Home > Laptops"


def test_parse_missing_fields_become_none():
    r = parse_product({"sku": 5})
    assert r["product_id"] == 5 and r["name"] is None and r["category"] is None


def test_parse_page_skips_bad_entries():
    recs, meta = parse_page({"products": [fake_product(1), {"name": "no sku"}, "junk"], "total": 3})
    assert len(recs) == 1 and meta["skipped"] == 2


@pytest.mark.parametrize("bad", [None, [], {"products": "x"}, {}])
def test_parse_page_malformed(bad):
    with pytest.raises(E.MalformedResponse):
        parse_page(bad)


# ---------- UNIT: output ----------
def test_write_outputs(tmp_path):
    recs = [parse_product(fake_product(i)) for i in range(3)]
    c, j = write_outputs(recs, str(tmp_path), "search=x", {"a": 1})
    rows = list(csv.DictReader(open(c, encoding="utf-8")))
    assert len(rows) == 3 and list(rows[0].keys()) == RECORD_FIELDS
    assert json.load(open(j, encoding="utf-8"))["count"] == 3


# ---------- UNIT: config ----------
def test_proxy_unset_is_none():
    assert proxies_from_env({}) is None


def test_proxy_valid_and_https_falls_back_to_http():
    p = proxies_from_env({"SCRAPER_HTTP_PROXY": "http://u:p@host:8080"})
    assert p == {"http": "http://u:p@host:8080", "https": "http://u:p@host:8080"}


@pytest.mark.parametrize("val", ["host:8080", "ftp://h:1", "http://", "http://h:notaport"])
def test_proxy_malformed_rejected(val):
    with pytest.raises(E.ConfigError):
        proxies_from_env({"SCRAPER_HTTP_PROXY": val})


def test_missing_key_rejected():
    with pytest.raises(E.ConfigError):
        Config.from_env({}).require_key()


def test_bad_number_rejected():
    with pytest.raises(E.ConfigError):
        Config.from_env({"SCRAPER_TIMEOUT": "abc"})


def test_repr_hides_key_and_proxy():
    c = Config(api_key=KEY, proxies={"http": "http://u:p@h:1"})
    assert KEY not in repr(c) and "u:p" not in repr(c)


# ---------- UNIT: redaction / classification ----------
def test_redact():
    assert KEY not in redact(f"https://x/y?apiKey={KEY}&a=1")


def test_classify_403():
    assert classify_403("Over quota: call limit exceeded") is E.QuotaExhausted
    assert classify_403("Invalid API key") is E.AuthError
    assert classify_403("nope") is E.ForbiddenError


def test_url_builder_has_no_key():
    assert KEY not in products_url("https://api.bestbuy.com/v1", "search=laptop")


# ---------- SIMULATED: end-to-end extraction ----------
def test_sim_pagination_200():
    srv, base = start_in_thread(total=60)
    tr = fast()
    recs, summary = extract_products(tr, cfg(base), "search=x", max_records=50, page_size=20, max_pages=5)
    assert len(recs) == 50 and summary["pages_fetched"] == 3
    assert all(e["status"] == 200 for e in tr.events)
    assert all(KEY not in e["url"] for e in tr.events)
    srv.shutdown()


def test_sim_stops_at_last_page():
    srv, base = start_in_thread(total=7)
    recs, summary = extract_products(fast(), cfg(base), "search=x", max_records=100, page_size=5, max_pages=9)
    assert len(recs) == 7
    srv.shutdown()


# ---------- SIMULATED: error handling ----------
def test_sim_403_auth_not_retried():
    srv, base = start_in_thread()
    tr = fast()
    with pytest.raises(E.AuthError):
        tr.get_json(base + "/forbidden")
    assert len(tr.events) == 1   # no retry
    srv.shutdown()


def test_sim_500_retried_then_fails():
    srv, base = start_in_thread()
    tr = fast(max_retries=2)
    with pytest.raises(E.ServerError):
        tr.get_json(base + "/error")
    assert len(tr.events) == 3   # 1 try + 2 retries, then stop
    srv.shutdown()


def test_sim_timeout():
    srv, base = start_in_thread()
    tr = fast(timeout=0.5, max_retries=0)
    with pytest.raises(E.TransportError):
        tr.get_json(base + "/slow")
    assert tr.events[-1]["outcome"] == "TransportError"
    srv.shutdown()


def test_sim_malformed_json():
    srv, base = start_in_thread()
    with pytest.raises(E.MalformedResponse):
        fast().get_json(base + "/badjson")
    srv.shutdown()


def test_connection_refused():
    with pytest.raises(E.TransportError):
        fast(max_retries=0, timeout=1).get_json("http://127.0.0.1:9/x")


# ---------- SIMULATED: rate limiting ----------
def test_sim_429_respects_retry_after_then_gives_up():
    srv, base = start_in_thread(limit=2, over="429", retry_after=3)
    sleeps = []
    tr = HttpTransport(delay=0, sleep=sleeps.append, max_retries=2)
    url = base + "/v1/products(search=x)"
    tr.get_json(url); tr.get_json(url)
    with pytest.raises(E.RateLimitError):
        tr.get_json(url)
    assert [e["status"] for e in tr.events] == [200, 200, 429, 429, 429]  # 2 bounded retries, then stop
    assert sleeps.count(3.0) == 2                                           # waited Retry-After each time
    srv.shutdown()


def test_sim_429_without_retry_after_stops_at_once():
    srv, base = start_in_thread(limit=0, over="429", retry_after="x")
    tr = fast()
    with pytest.raises(E.RateLimitError):
        tr.get_json(base + "/v1/products(search=x)")
    assert len(tr.events) == 1
    srv.shutdown()


def test_sim_429_retry_after_too_long_stops():
    srv, base = start_in_thread(limit=0, over="429", retry_after=999)
    tr = fast(max_retry_wait=30)
    with pytest.raises(E.RateLimitError):
        tr.get_json(base + "/v1/products(search=x)")
    assert len(tr.events) == 1
    srv.shutdown()


def test_sim_quota_exhausted_403_never_retried():
    srv, base = start_in_thread(limit=1, over="403")
    tr = fast()
    url = base + "/v1/products(search=x)"
    tr.get_json(url)
    with pytest.raises(E.QuotaExhausted):
        tr.get_json(url)
    assert [e["status"] for e in tr.events] == [200, 403]
    srv.shutdown()


def test_request_log_written(tmp_path):
    srv, base = start_in_thread(limit=0, over="429", retry_after=1)
    tr = fast(max_retries=1)
    with pytest.raises(E.RateLimitError):
        tr.get_json(base + "/v1/products(search=x)", {"apiKey": KEY})
    p = tmp_path / "log.csv"
    write_request_log(tr.events, str(p))
    text = p.read_text()
    assert "429" in text and "retry-after" in text and KEY not in text
    srv.shutdown()


# ---------- MOCKED: status mapping without a server ----------
class FakeResp:
    def __init__(self, code, body="", headers=None):
        self.status_code, self.text, self.headers = code, body, headers or {}

    def json(self):
        return json.loads(self.text)


@pytest.mark.parametrize("code,exc", [(401, E.AuthError), (404, E.ClientError), (400, E.ClientError),
                                      (503, E.ServerError)])
def test_mocked_status_mapping(code, exc):
    tr = fast(max_retries=0)
    tr.session.get = lambda *a, **k: FakeResp(code, "x")
    with pytest.raises(exc):
        tr.get_json("http://x/y")


def test_mocked_200():
    tr = fast()
    tr.session.get = lambda *a, **k: FakeResp(200, '{"a": 1}')
    assert tr.get_json("http://x/y") == {"a": 1}


# ---------- SIMULATED proxy: a local stub that plays the proxy role ----------
def test_proxy_config_routes_through_stub_proxy():
    seen = []

    class P(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append(self.path)   # a forward proxy receives the absolute URL
            body = json.dumps({"products": [fake_product(1)], "total": 1, "totalPages": 1}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    proxy = HTTPServer(("127.0.0.1", 0), P)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    env = {"SCRAPER_HTTP_PROXY": f"http://127.0.0.1:{proxy.server_address[1]}", "BESTBUY_API_KEY": KEY,
           "BESTBUY_BASE_URL": "http://api.example.invalid/v1", "SCRAPER_DELAY": "0.25"}
    c = Config.from_env(env)
    tr = HttpTransport(c.timeout, 0, c.proxies)
    recs, _ = extract_products(tr, c, "search=x", max_records=5)
    assert len(recs) == 1
    assert seen and seen[0].startswith("http://api.example.invalid/v1/products")
    proxy.shutdown()


def test_works_without_proxy():
    srv, base = start_in_thread()
    recs, _ = extract_products(fast(proxies=None), cfg(base), "search=x", max_records=3, page_size=3)
    assert len(recs) == 3
    srv.shutdown()
