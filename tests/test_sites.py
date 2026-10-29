"""UNIT tests for the second site (real captured HTML) and the site registry."""
import pytest

from bestbuy_scraper.errors import MalformedResponse
from htmlscraper.extractor import scrape_listing
from htmlscraper.sim_site import make_site
from htmlscraper.sites import SITES, parse_countries
from htmlscraper.transport import HtmlTransport
import os, threading

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "scrapethissite_countries_REAL_captured_2026-10-29.html")
HTML = open(FIX, encoding="utf-8").read()


def test_parse_countries_real_page():
    recs, nxt = parse_countries(HTML, "https://www.scrapethissite.com/pages/simple/")
    assert len(recs) == 250 and nxt is None
    assert recs[0] == {"name": "Andorra", "capital": "Andorra la Vella", "population": 84000.0,
                       "area_km2": 468.0, "url": "https://www.scrapethissite.com/pages/simple/"}


def test_parse_countries_rejects_block_page():
    with pytest.raises(MalformedResponse):
        parse_countries("<html>Too many requests</html>", "http://x")


def test_registry_respects_documented_pace():
    assert SITES["scrapethissite_countries"].min_delay >= 1.5   # site documents max 1 request/second
    for s in SITES.values():
        assert s.min_delay >= 1.0 and s.fields and callable(s.parse)


def test_scrape_with_second_parser_over_local_server():
    # SIMULATED server serving the REAL captured countries page
    srv = make_site(fixture=FIX, path="/pages/simple/")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    t = HtmlTransport(delay=0, sleep=lambda s: None)
    recs, summ = scrape_listing(t, base + "/pages/simple/", parse=parse_countries)
    assert len(recs) == 100                          # capped by max_records default
    assert summ["stopped_with"] is None
    srv.shutdown()
