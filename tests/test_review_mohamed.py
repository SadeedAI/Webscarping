"""Review tests for Mohamed's HealthProxyProvider: end-to-end through the real transport,
env wiring, and edge cases his own tests don't cover. Local stubs only, no network."""
import pytest

from bestbuy_scraper import errors as E
from htmlscraper.extractor import scrape_listing
from htmlscraper.my_provider import HealthProxyProvider
from htmlscraper.proxy_iface import ProxyPool, provider_from_env
from htmlscraper.sim_site import PATH
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from test_html import StubProxy, tr  # noqa: E402

SITE = "http://shop.example.invalid" + PATH


# ---------- E2E through HtmlTransport ----------
def test_e2e_failover_bad_then_good():
    bad, good = StubProxy("403"), StubProxy("ok")
    t = tr(HealthProxyProvider([bad.url, good.url]), failover=True)
    recs, summ = scrape_listing(t, SITE, max_pages=1)
    assert len(recs) == 6 and summ["stopped_with"] is None
    assert [e["status"] for e in t.events if PATH in e["url"]] == [403, 200]
    bad.srv.shutdown(); good.srv.shutdown()


def test_e2e_all_blocked_stops_cleanly():
    a, b, c = StubProxy("403"), StubProxy("403"), StubProxy("403")
    t = tr(HealthProxyProvider([a.url, b.url, c.url]), failover=True, max_failovers=10)
    recs, summ = scrape_listing(t, SITE, max_pages=1)
    assert recs == [] and summ["stopped_with"]
    assert len([e for e in t.events if e["status"] == 403 and PATH in e["url"]]) == 3


def test_e2e_failover_off_never_touches_second_proxy():
    bad, good = StubProxy("403"), StubProxy("ok")
    t = tr(HealthProxyProvider([bad.url, good.url]))
    recs, summ = scrape_listing(t, SITE, max_pages=1)
    assert recs == [] and not good.seen


def test_e2e_dead_proxy_failover_switches_route():
    """A proxy that is down (connection refused) is reported and rotated away from."""
    good = StubProxy("ok")
    p = HealthProxyProvider(["http://127.0.0.1:9", good.url])
    t = tr(p, failover=True, timeout=2)
    recs, summ = scrape_listing(t, SITE, max_pages=1)
    assert len(recs) == 6 and summ["stopped_with"] is None
    assert t.events[0]["outcome"] == "ProxyConnectError" and good.seen
    assert "http://127.0.0.1:9" in p._rest_until          # dead proxy now rests
    good.srv.shutdown()


def test_e2e_dead_proxy_without_failover_retries_then_stops():
    good = StubProxy("ok")
    t = tr(HealthProxyProvider(["http://127.0.0.1:9", good.url]), max_retries=1, timeout=2)
    recs, summ = scrape_listing(t, SITE, max_pages=1)
    assert recs == [] and "ProxyConnectError" in summ["stopped_with"]
    assert [e["outcome"] for e in t.events] == ["ProxyConnectError"] * 2 and not good.seen
    good.srv.shutdown()


def test_e2e_proxy_wrong_password_stops_without_retry():
    bad = StubProxy("407")
    t = tr(HealthProxyProvider([bad.url]), failover=True)
    recs, summ = scrape_listing(t, SITE, max_pages=1)
    assert recs == [] and "ProxyAuthError" in summ["stopped_with"]
    assert len([e for e in t.events if PATH in e["url"]]) == 1     # no pointless retries
    bad.srv.shutdown()


def test_e2e_proxy_wrong_password_failover_to_next():
    bad, good = StubProxy("407"), StubProxy("ok")
    t = tr(HealthProxyProvider([bad.url, good.url]), failover=True)
    recs, summ = scrape_listing(t, SITE, max_pages=1)
    assert len(recs) == 6 and summ["stopped_with"] is None
    bad.srv.shutdown(); good.srv.shutdown()


def test_e2e_all_proxies_dead_stops_cleanly():
    t = tr(HealthProxyProvider(["http://127.0.0.1:9", "http://127.0.0.1:7"]), failover=True, timeout=2)
    recs, summ = scrape_listing(t, SITE, max_pages=1)
    assert recs == [] and "ProxyConnectError" in summ["stopped_with"]


# ---------- env wiring ----------
def test_env_selects_mohamed_provider():
    p = provider_from_env({"SCRAPER_MY_PROXY_LIST": "http://a:1, http://b:2"})
    assert isinstance(p, HealthProxyProvider) and len(p.urls) == 2


def test_env_mohamed_has_priority_over_pool():
    p = provider_from_env({"SCRAPER_MY_PROXY_LIST": "http://a:1", "SCRAPER_PROXY_LIST": "http://b:2"})
    assert isinstance(p, HealthProxyProvider)


def test_env_bad_url_rejected():
    with pytest.raises(E.ConfigError):
        provider_from_env({"SCRAPER_MY_PROXY_LIST": "http://a:1,notaproxy"})


def test_env_empty_falls_back():
    assert isinstance(provider_from_env({"SCRAPER_MY_PROXY_LIST": " , "}), type(provider_from_env({})))


# ---------- edge cases ----------
def test_cooldown_escalates_and_caps_at_4x():
    now = [0.0]
    p = HealthProxyProvider(["http://a:1", "http://b:2"], cooldown=100, clock=lambda: now[0])
    for _ in range(6):
        p.report_blocked("http://a:1", 403)
    assert p._rest_until["http://a:1"] == 400          # capped at 4x


def test_single_proxy_never_rotates():
    p = HealthProxyProvider(["http://a:1"])
    p.report_blocked("http://a:1", 403)
    assert p.rotate() is False


def test_empty_list_raises():
    with pytest.raises(E.ConfigError):
        HealthProxyProvider([])


def test_describe_never_leaks_password():
    p = HealthProxyProvider(["http://user:S3cret@10.0.0.1:8080"])
    assert "S3cret" not in p.describe() and "user" not in p.describe()


def test_rotate_skips_resting_and_wraps():
    now = [0.0]
    p = HealthProxyProvider(["http://a:1", "http://b:2", "http://c:3"], cooldown=100, clock=lambda: now[0])
    p.report_blocked("http://b:2", 403)                 # b rests
    p.report_blocked("http://a:1", 403)
    assert p.rotate() and p.current() == "http://c:3"   # skips b


def test_behaves_same_as_reference_pool_on_first_block():
    urls = ["http://a:1", "http://b:2", "http://c:3"]
    mine, ref = HealthProxyProvider(urls), ProxyPool(urls)
    for x in (mine, ref):
        x.report_blocked(x.current(), 403); x.rotate()
    assert mine.current() == ref.current()
