"""PROXY-INTERFACE CONTRACT TESTS (no network, no real proxy needed).

Runs against the built-in providers. Mohamed runs it against his own provider:
    $env:SCRAPER_PROVIDER_FACTORY = "my_provider:make_provider"      # module:callable returning a ProxyProvider
    $env:PYTHONPATH = "src"
    .\\.venv\\bin\\python.exe -m pytest tests/test_provider_contract.py -q
The factory should return a provider with AT LEAST 2 routes if it supports rotation.
Passing proves the interface is respected. It does NOT prove the proxies work (see the live acceptance tests).
"""
import importlib
import os
from urllib.parse import urlparse

import pytest

from htmlscraper.proxy_iface import NoProxy, ProxyPool, ProxyProvider, StaticProxy


def _external():
    spec = os.environ.get("SCRAPER_PROVIDER_FACTORY")
    if not spec:
        return []
    mod, fn = spec.split(":")
    return [getattr(importlib.import_module(mod), fn)]


FACTORIES = [NoProxy, lambda: StaticProxy("http://127.0.0.1:9"),
             lambda: ProxyPool(["http://127.0.0.1:1", "http://127.0.0.1:2", "http://127.0.0.1:3"])] + _external()


@pytest.fixture(params=FACTORIES)
def prov(request):
    p = request.param()
    assert isinstance(p, ProxyProvider)
    return p


def test_current_is_none_or_http_url(prov):
    c = prov.current()
    assert c is None or (isinstance(c, str) and urlparse(c).scheme in ("http", "https") and urlparse(c).hostname)


def test_reports_never_raise(prov):
    c = prov.current()
    prov.report_success(c)
    for status in (403, 429, None):
        prov.report_blocked(c, status)


def test_rotate_returns_bool_and_eventually_false(prov):
    """Must not return True forever: once routes are exhausted it MUST say False so the scraper stops."""
    for _ in range(50):
        prov.report_blocked(prov.current(), 403)
        r = prov.rotate("test")
        assert isinstance(r, bool)
        if r is False:
            return
    pytest.fail("rotate() kept returning True after 50 blocked routes: scraper could loop")


def test_after_rotate_true_route_changes(prov):
    before = prov.current()
    prov.report_blocked(before, 429)
    if prov.rotate("test"):
        assert prov.current() != before


def test_describe_has_no_credentials(prov):
    assert "@" not in prov.describe()
