"""HTML transport: pacing, robots.txt, timeouts, exponential backoff, Retry-After, proxy hook.

Owned by Shehab. The proxy side is only the ProxyProvider interface (see proxy_iface.py).
Rules for blocked requests (403 / 429):
  1. 429 with a usable Retry-After (<= max_retry_wait): wait that long, retry (bounded).
  2. Otherwise, only if failover is enabled AND the provider can rotate: switch route, retry (bounded).
  3. Otherwise stop with a typed error. 403 is never retried on the same route.
"""
import email.utils
import logging
import random
import re
import time
from typing import Dict, Optional
from urllib import robotparser
from urllib.parse import urlparse

import requests

from bestbuy_scraper import errors as E
from .proxy_iface import NoProxy, ProxyProvider

log = logging.getLogger("htmlscraper.http")
_KEY_RE = re.compile(r"((?:api_?key|token|password)=)[^&\s]+", re.I)
_CRED_RE = re.compile(r"//[^/@\s]+:[^/@\s]+@")


def redact(text) -> str:
    return _CRED_RE.sub("//***:***@", _KEY_RE.sub(r"\1***", str(text)))


def parse_retry_after(v, now=None) -> Optional[float]:
    """Seconds from a Retry-After header (number or HTTP-date). None if missing/unusable."""
    if v is None:
        return None
    try:
        return max(0.0, float(v))
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(v)
        return max(0.0, dt.timestamp() - (now if now is not None else time.time()))
    except (TypeError, ValueError):
        return None


class HtmlTransport:
    def __init__(self, provider: Optional[ProxyProvider] = None, timeout=15.0, delay=2.0,
                 max_retries=3, backoff_base=2.0, max_retry_wait=60.0, failover=False,
                 max_failovers=2, sleep=time.sleep, jitter=True, respect_robots=True,
                 user_agent="class-project-scraper/1.0 (student; contact: shehapsherif11@gmail.com)"):
        self.provider = provider or NoProxy()
        self.timeout, self.delay = timeout, delay
        self.max_retries, self.backoff_base = max_retries, backoff_base
        self.max_retry_wait, self.failover, self.max_failovers = max_retry_wait, failover, max_failovers
        self._sleep, self.jitter, self.respect_robots = sleep, jitter, respect_robots
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.session.trust_env = False
        self._last = 0.0
        self._robots: Dict[str, robotparser.RobotFileParser] = {}
        self.events = []

    # ----- robots.txt -----
    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        rp = self._robots.get(origin)
        if rp is None:
            rp = robotparser.RobotFileParser()
            try:
                body = self._request(origin + "/robots.txt", check_robots=False)
                rp.parse(body.splitlines())
            except E.HttpStatusError as e:
                if e.status == 404:
                    rp.parse([])          # no robots.txt: everything allowed
                else:
                    rp.parse(["User-agent: *", "Disallow: /"])   # cannot read rules: be cautious
            self._robots[origin] = rp
        return rp.can_fetch(self.user_agent, url)

    # ----- main entry -----
    def get_text(self, url: str) -> str:
        if not self.allowed(url):
            raise E.ForbiddenError(f"robots.txt disallows {redact(url)}; not fetched", None)
        return self._request(url)

    def _pace(self):
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)

    def _request(self, url, check_robots=True) -> str:
        attempt, failovers = 0, 0
        while True:
            self._pace()
            proxy = self.provider.current()
            start = time.monotonic()
            status, hdrs = None, {}
            try:
                try:
                    r = self.session.get(url, timeout=self.timeout,
                                         proxies={"http": proxy, "https": proxy} if proxy else None)
                except requests.Timeout as e:
                    raise E.TransportError(f"timeout after {self.timeout}s") from e
                except requests.RequestException as e:
                    raise E.TransportError(f"connection error: {type(e).__name__}") from e
                finally:
                    self._last = time.monotonic()
                status = r.status_code
                hdrs = {k: r.headers[k] for k in ("Retry-After",) if k in r.headers}
                if status == 200:
                    self._log(url, proxy, status, "ok", start, hdrs, "")
                    self.provider.report_success(proxy)
                    return r.text
                self._raise(r)
            except E.ScraperError as err:
                self._log(url, proxy, status, type(err).__name__, start, hdrs, str(err))
                if isinstance(err, (E.RateLimitError, E.ForbiddenError, E.QuotaExhausted, E.AuthError)):
                    self.provider.report_blocked(proxy, status)
                action, wait = self._decide(err, attempt, failovers)
                if action == "stop":
                    raise
                if action == "rotate":
                    failovers += 1
                log.warning("%s -> %s after %.1fs (retry %d/%d)", type(err).__name__, action, wait,
                            attempt + 1, self.max_retries)
                self._sleep(wait)
                attempt += 1

    def _raise(self, r):
        ra = parse_retry_after(r.headers.get("Retry-After"))
        msg = f"HTTP {r.status_code}"
        c = r.status_code
        if c == 429:
            raise E.RateLimitError(msg, c, ra)
        if c == 403:
            raise E.ForbiddenError(msg, c, ra)
        if c == 401:
            raise E.AuthError(msg, c)
        if c >= 500:
            raise E.ServerError(msg, c, ra)
        raise E.ClientError(msg, c)

    def _backoff(self, attempt) -> float:
        d = min(self.backoff_base * (2 ** attempt), self.max_retry_wait)
        return d * random.uniform(0.5, 1.0) if self.jitter else d

    def _decide(self, err, attempt, failovers):
        """Return (action, wait_seconds). action: retry | rotate | stop."""
        if attempt >= self.max_retries:
            return "stop", 0
        if isinstance(err, E.RateLimitError):
            if err.retry_after is not None and err.retry_after <= self.max_retry_wait:
                return "retry", max(err.retry_after, 1.0)
        if isinstance(err, (E.RateLimitError, E.ForbiddenError)):
            if self.failover and failovers < self.max_failovers and self.provider.rotate(type(err).__name__):
                return "rotate", self._backoff(attempt)   # provider switched route; wait, then retry
            return "stop", 0                              # no failover, or no other route: give up
        if isinstance(err, (E.ServerError, E.TransportError)):
            return "retry", self._backoff(attempt)
        return "stop", 0

    def _log(self, url, proxy, status, outcome, start, hdrs, msg):
        ev = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "url": redact(url), "status": status,
              "outcome": outcome, "ms": round((time.monotonic() - start) * 1000, 1),
              "retry_after": hdrs.get("Retry-After", ""), "proxy": "yes" if proxy else "no",
              "error": redact(msg)}
        self.events.append(ev)
        log.info("%s status=%s outcome=%s ms=%s proxy=%s", ev["url"], status, outcome, ev["ms"], ev["proxy"])
