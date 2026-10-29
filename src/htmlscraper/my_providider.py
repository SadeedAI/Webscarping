"""Mohamed Samy's proxy provider: pool with per-proxy cooldown and safe describe().

Subclasses ProxyProvider (the contract in proxy_iface.py). No network access here:
the scraper's transport decides when to call these methods.
"""
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

from bestbuy_scraper.config import validate_proxy_url
from bestbuy_scraper.errors import ConfigError

from .proxy_iface import ProxyProvider


def _safe_label(url: str) -> str:
    """host:port only, never user:pass."""
    p = urlparse(url)
    return f"{p.hostname}:{p.port}" if p.hostname else "invalid"


class HealthProxyProvider(ProxyProvider):
    """Round-robin pool. A blocked proxy rests for `cooldown` seconds (longer on repeated blocks, max 4x)."""

    def __init__(self, urls: List[str], cooldown: float = 300.0, clock=time.monotonic):
        if not urls:
            raise ConfigError("proxy list is empty")
        self.urls = [validate_proxy_url(u, "proxy list entry") for u in urls]
        self.cooldown, self._clock = cooldown, clock
        self._i = 0
        self._rest_until: Dict[str, float] = {}
        self._fails: Dict[str, int] = {u: 0 for u in self.urls}

    def _rested(self, url: str) -> bool:
        return self._rest_until.get(url, 0) > self._clock()

    def current(self) -> Optional[str]:
        return self.urls[self._i]

    def report_success(self, proxy: Optional[str]) -> None:
        # proxy can be None (direct connection) or unknown: ignore safely
        if proxy in self._fails:
            self._fails[proxy] = 0
            self._rest_until.pop(proxy, None)

    def report_blocked(self, proxy: Optional[str], status: Optional[int]) -> None:
        if proxy in self._fails:
            self._fails[proxy] += 1
            factor = min(self._fails[proxy], 4)
            self._rest_until[proxy] = self._clock() + self.cooldown * factor

    def rotate(self, reason: str = "") -> bool:
        n = len(self.urls)
        for step in range(1, n):
            j = (self._i + step) % n
            if not self._rested(self.urls[j]):
                self._i = j
                return True
        return False  # no loop, no waiting: the scraper stops

    def describe(self) -> str:
        return (f"HealthProxyProvider(active={_safe_label(self.urls[self._i])}, "
                f"{len(self.urls)} proxies)")


def make_provider() -> ProxyProvider:
    """Factory for the contract test (SCRAPER_PROVIDER_FACTORY=my_provider:make_provider).
    Fake local URLs, no real connection is made."""
    return HealthProxyProvider([
        "http://u1:p1@127.0.0.1:8001",
        "http://u2:p2@127.0.0.1:8002",
        "http://u3:p3@127.0.0.1:8003",
    ])
