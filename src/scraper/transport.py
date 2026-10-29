"""HTTP transport layer. Only this file knows about proxies.

Mohamed's proxy layer plugs in here via env vars (no scraping code changes).
"""
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

import requests

log = logging.getLogger(__name__)

RATE_HEADERS = ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset")


class TransportError(Exception):
    """Network-level failure (timeout, connection error). Not an HTTP status."""


@dataclass
class Response:
    url: str
    status: int
    text: str
    elapsed: float
    headers: Dict[str, str] = field(default_factory=dict)


def proxies_from_env() -> Optional[Dict[str, str]]:
    """Read SCRAPER_HTTP_PROXY / SCRAPER_HTTPS_PROXY. Return None if unset."""
    http = os.getenv("SCRAPER_HTTP_PROXY")
    https = os.getenv("SCRAPER_HTTPS_PROXY") or http
    proxies = {}
    if http:
        proxies["http"] = http
    if https:
        proxies["https"] = https
    return proxies or None


class HttpTransport:
    def __init__(self, timeout: float = 10.0, delay: float = 1.0,
                 proxies: Optional[Dict[str, str]] = None,
                 user_agent: str = "student-scraper/1.0 (educational project)"):
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        # trust_env=False: ignore system proxy vars; only use the explicit setting.
        self.session.trust_env = False
        if proxies:
            self.session.proxies.update(proxies)
            log.info("Proxy enabled for schemes: %s", sorted(proxies))
        self._last = 0.0

    def get(self, url: str) -> Response:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        start = time.monotonic()
        try:
            r = self.session.get(url, timeout=self.timeout)
        except requests.Timeout as e:
            raise TransportError(f"timeout after {self.timeout}s: {url}") from e
        except requests.ConnectionError as e:
            raise TransportError(f"connection error: {url}: {e}") from e
        finally:
            self._last = time.monotonic()
        elapsed = time.monotonic() - start
        r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
        headers = {h: r.headers[h] for h in RATE_HEADERS if h in r.headers}
        return Response(url=url, status=r.status_code, text=r.text, elapsed=elapsed, headers=headers)
