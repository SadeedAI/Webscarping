"""PROXY CONTRACT (Mohamed Samy owns real implementations).

The scraper never touches proxies directly. It asks a ProxyProvider:
  - current()           -> proxy URL to use for the next request, or None for a direct connection
  - report_success(p)   -> the request through proxy `p` worked
  - report_blocked(p, status) -> the site answered 403/429 (or the proxy itself failed) via `p`
  - rotate(reason)      -> switch to another proxy; return True if a different one is now active,
                           False if none is available (the scraper then stops, it does not loop)

Nothing here guarantees recovery from a block. A provider may only make the next attempt come from
a different route. Use it only where the target site's rules allow it.
The classes below are small reference implementations that work with local stub proxies in tests.
"""
import os
import time
from typing import Dict, List, Optional

from bestbuy_scraper.config import validate_proxy_url
from bestbuy_scraper.errors import ConfigError


class ProxyProvider:
    """Base class and the contract. Subclass this."""

    def current(self) -> Optional[str]:
        return None

    def report_success(self, proxy: Optional[str]) -> None:
        pass

    def report_blocked(self, proxy: Optional[str], status: Optional[int]) -> None:
        pass

    def rotate(self, reason: str = "") -> bool:
        return False

    def describe(self) -> str:
        return type(self).__name__


class NoProxy(ProxyProvider):
    """Direct connection (default)."""


class StaticProxy(ProxyProvider):
    """One fixed proxy. Cannot rotate."""

    def __init__(self, url: str):
        self.url = validate_proxy_url(url, "proxy")

    def current(self):
        return self.url


class ProxyPool(ProxyProvider):
    """Round-robin over a list. A proxy that was blocked rests for `cooldown` seconds."""

    def __init__(self, urls: List[str], cooldown: float = 300.0, clock=time.monotonic):
        if not urls:
            raise ConfigError("proxy list is empty")
        self.urls = [validate_proxy_url(u, "proxy list entry") for u in urls]
        self.cooldown, self._clock = cooldown, clock
        self._i = 0
        self._rest_until: Dict[str, float] = {}

    def current(self):
        return self.urls[self._i]

    def report_blocked(self, proxy, status):
        if proxy:
            self._rest_until[proxy] = self._clock() + self.cooldown

    def rotate(self, reason=""):
        for step in range(1, len(self.urls)):
            cand = self.urls[(self._i + step) % len(self.urls)]
            if self._rest_until.get(cand, 0) <= self._clock():
                self._i = (self._i + step) % len(self.urls)
                return True
        return False

    def describe(self):
        return f"ProxyPool({len(self.urls)} proxies)"


def provider_from_env(env=None) -> ProxyProvider:
    """SCRAPER_PROXY_LIST (comma separated) > SCRAPER_HTTP_PROXY > none."""
    env = os.environ if env is None else env
    mine = [x.strip() for x in (env.get("SCRAPER_MY_PROXY_LIST") or "").split(",") if x.strip()]
    if mine:
        from .my_provider import HealthProxyProvider  # local import avoids circular import
        return HealthProxyProvider(mine)
    lst = [x.strip() for x in (env.get("SCRAPER_PROXY_LIST") or "").split(",") if x.strip()]
    if lst:
        return ProxyPool(lst)
    one = (env.get("SCRAPER_HTTPS_PROXY") or env.get("SCRAPER_HTTP_PROXY") or "").strip()
    return StaticProxy(one) if one else NoProxy()
