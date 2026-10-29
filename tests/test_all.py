import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from scraper.cli import fetch
from scraper.parser import parse_detail, parse_listing
from scraper.test_server import make_server
from scraper.transport import HttpTransport, TransportError, proxies_from_env

LISTING = """
<article class="product_pod"><h3><a href="a_1/index.html" title="Book A">Book...</a></h3>
<p class="star-rating Three"></p><p class="price_color">£12.50</p>
<p class="availability"> In stock </p></article>
<article class="product_pod"><h3><a title="Broken"></a></h3></article>
<li class="next"><a href="page-2.html">next</a></li>
"""


def start(srv):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


# ---- parser ----
def test_parse_listing_fields():
    books, nxt = parse_listing(LISTING, "https://x.test/catalogue/page-1.html")
    assert books[0] == {"title": "Book A", "price_gbp": 12.5, "rating": 3, "in_stock": True,
                        "url": "https://x.test/catalogue/a_1/index.html"}
    assert nxt == "https://x.test/catalogue/page-2.html"


def test_parse_missing_fields_become_none():
    b = parse_listing(LISTING, "https://x.test/")[0][1]
    assert b["price_gbp"] is None and b["rating"] is None and b["in_stock"] is None and b["url"] is None


def test_parse_unexpected_html():
    assert parse_listing("<html>nothing</html>", "https://x.test/") == ([], None)
    assert parse_detail("<html></html>") == {"category": None}


# ---- rate limit ----
def test_429_after_limit_and_reset():
    srv = make_server(limit=3, window=2)
    base = start(srv)
    tp = HttpTransport(timeout=3, delay=0)
    codes = [tp.get(base + "/").status for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    r = tp.get(base + "/")
    assert "retry-after" in r.headers
    import time; time.sleep(2.2)
    assert tp.get(base + "/").status == 200
    srv.shutdown()


def test_403_and_500_are_not_429_and_not_retried():
    srv = make_server()
    base = start(srv)
    tp = HttpTransport(timeout=3, delay=0)
    assert tp.get(base + "/forbidden").status == 403
    assert fetch(tp, base + "/forbidden") is None
    assert fetch(tp, base + "/error") is None
    srv.shutdown()


def test_timeout_raises_transport_error():
    srv = make_server()
    base = start(srv)
    with pytest.raises(TransportError):
        HttpTransport(timeout=0.5, delay=0).get(base + "/slow")
    srv.shutdown()


def test_connection_refused_raises_transport_error():
    with pytest.raises(TransportError):
        HttpTransport(timeout=1, delay=0).get("http://127.0.0.1:1/")


# ---- proxy interface ----
def test_proxy_env_optional(monkeypatch):
    for k in ("SCRAPER_HTTP_PROXY", "SCRAPER_HTTPS_PROXY"):
        monkeypatch.delenv(k, raising=False)
    assert proxies_from_env() is None
    monkeypatch.setenv("SCRAPER_HTTP_PROXY", "http://h:1")
    assert proxies_from_env() == {"http": "http://h:1", "https": "http://h:1"}


def test_requests_go_through_mock_proxy():
    seen = []

    class P(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            seen.append(self.path)  # a forward proxy receives the absolute URL
            self.send_response(200); self.send_header("Content-Length", "7"); self.end_headers()
            self.wfile.write(b"proxied")

    proxy = HTTPServer(("127.0.0.1", 0), P)
    purl = start(proxy)
    tp = HttpTransport(timeout=3, delay=0, proxies={"http": purl})
    r = tp.get("http://example.invalid/page")
    assert r.status == 200 and r.text == "proxied"
    assert seen == ["http://example.invalid/page"]
    proxy.shutdown()
