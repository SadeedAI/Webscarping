"""HTTP transport. The ONLY module that knows about proxies, retries and secrets.

Parsing and extraction code call `get_json()` and never see the proxy.
Mohamed's proxy layer plugs in through Config.proxies (SCRAPER_*_PROXY) or by
changing `_make_session`.
"""
import logging
import re
import time
from typing import Any, Dict, Optional

import requests

from . import errors as E

log = logging.getLogger("bestbuy.http")

_KEY_RE = re.compile(r"(apikey=)[^&\s'\"]+", re.I)
RATE_HEADERS = ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset")


def redact(text: str) -> str:
    """Hide api keys inside any URL or message before it is logged."""
    return _KEY_RE.sub(r"\1***", str(text))


def classify_403(body_text: str) -> type:
    low = (body_text or "").lower()
    if any(w in low for w in ("limit", "quota", "exceed")):
        return E.QuotaExhausted
    if any(w in low for w in ("key", "invalid", "inactive", "unauthor")):
        return E.AuthError
    return E.ForbiddenError


def _parse_retry_after(v):
    if v is None:
        return None
    try:
        return max(0.0, float(v))
    except ValueError:
        return None   # HTTP-date form: treated as unusable; caller stops instead of guessing


class HttpTransport:
    def __init__(self, timeout=15.0, delay=0.5, proxies: Optional[Dict[str, str]] = None,
                 max_retries=2, max_retry_wait=30.0, sleep=time.sleep,
                 user_agent="bestbuy-api-client/1.0 (student project)"):
        self.timeout, self.delay = timeout, delay
        self.max_retries, self.max_retry_wait = max_retries, max_retry_wait
        self._sleep = sleep
        self._last = 0.0
        self.session = self._make_session(proxies, user_agent)
        self.events = []   # one dict per HTTP attempt, used for rate-limit logs

    @staticmethod
    def _make_session(proxies, user_agent):
        s = requests.Session()
        s.headers["User-Agent"] = user_agent
        s.headers["Accept"] = "application/json"
        s.trust_env = False  # ignore system proxy vars: only explicit config is used
        if proxies:
            s.proxies.update(proxies)
            log.info("proxy enabled for schemes: %s", sorted(proxies))
        return s

    def _pace(self):
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)

    def _raise_for(self, r):
        retry_after = _parse_retry_after(r.headers.get("Retry-After"))
        code, body = r.status_code, r.text[:500]
        msg = f"HTTP {code}: {redact(body)[:200]}"
        if code == 429:
            raise E.RateLimitError(msg, code, retry_after)
        if code == 403:
            raise classify_403(body)(msg, code, retry_after)
        if code == 401:
            raise E.AuthError(msg, code)
        if code >= 500:
            raise E.ServerError(msg, code, retry_after)
        raise E.ClientError(msg, code)

    def _once(self, url, params):
        """One HTTP attempt. Returns (json, status, headers). Raises ScraperError."""
        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
        except requests.Timeout as e:
            raise E.TransportError(f"timeout after {self.timeout}s") from e
        except requests.RequestException as e:
            raise E.TransportError(f"connection error: {type(e).__name__}") from e
        finally:
            self._last = time.monotonic()
        self._cur_status = r.status_code
        self._cur_headers = {h: r.headers[h] for h in RATE_HEADERS if h in r.headers}
        if r.status_code != 200:
            self._raise_for(r)
        try:
            return r.json()
        except ValueError as e:
            raise E.MalformedResponse("200 response was not valid JSON") from e

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET and decode JSON. Retries only timeouts, 5xx and 429 (bounded)."""
        attempt = 0
        while True:
            self._pace()
            start = time.monotonic()
            self._cur_status, self._cur_headers = None, {}
            try:
                data = self._once(url, params)
            except E.ScraperError as err:
                self._record(url, start, type(err).__name__, str(err))
                wait = self._retry_wait(err, attempt)
                if wait is None:
                    raise
                log.warning("retrying in %.1fs (retry %d/%d)", wait, attempt + 1, self.max_retries)
                self._sleep(wait)
                attempt += 1
                continue
            self._record(url, start, "ok", "")
            return data

    def _retry_wait(self, err, attempt) -> Optional[float]:
        """Seconds to wait before a retry, or None to give up. 403 is never retried."""
        if attempt >= self.max_retries:
            return None
        if isinstance(err, E.RateLimitError):
            if err.retry_after is None or err.retry_after > self.max_retry_wait:
                return None   # no usable hint, or asked to wait too long: stop, do not hammer
            return max(err.retry_after, 1.0)
        if isinstance(err, (E.ServerError, E.TransportError)):
            return min(2.0 * (attempt + 1), self.max_retry_wait)
        return None

    def _record(self, url, start, outcome, msg):
        ev = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "url": redact(url),
              "status": self._cur_status, "outcome": outcome,
              "ms": round((time.monotonic() - start) * 1000, 1),
              "headers": self._cur_headers, "error": redact(msg)}
        self.events.append(ev)
        log.info("%s status=%s outcome=%s ms=%s %s", ev["url"], ev["status"], outcome, ev["ms"], ev["error"])
