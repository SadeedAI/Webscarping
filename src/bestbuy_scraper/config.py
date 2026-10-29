"""Configuration from environment variables. No secrets are stored in code."""
import os
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import urlparse

from .errors import ConfigError

DEFAULT_BASE_URL = "https://api.bestbuy.com/v1"


def load_dotenv(path: str = ".env") -> None:
    """Tiny .env reader (KEY=VALUE lines). The real environment wins."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def validate_proxy_url(value: str, name: str) -> str:
    p = urlparse(value)
    if p.scheme not in ("http", "https"):
        raise ConfigError(f"{name} must start with http:// or https:// (got scheme '{p.scheme}')")
    if not p.hostname:
        raise ConfigError(f"{name} has no host")
    try:
        _ = p.port
    except ValueError as e:
        raise ConfigError(f"{name} has a bad port") from e
    return value


def proxies_from_env(env=None) -> Optional[Dict[str, str]]:
    """SCRAPER_HTTP_PROXY / SCRAPER_HTTPS_PROXY -> requests-style dict, or None if unset."""
    env = os.environ if env is None else env
    http = (env.get("SCRAPER_HTTP_PROXY") or "").strip()
    https = (env.get("SCRAPER_HTTPS_PROXY") or "").strip() or http
    out = {}
    if http:
        out["http"] = validate_proxy_url(http, "SCRAPER_HTTP_PROXY")
    if https:
        out["https"] = validate_proxy_url(https, "SCRAPER_HTTPS_PROXY")
    return out or None


def _num(env, name, default, lo, hi):
    raw = env.get(name)
    if raw in (None, ""):
        return default
    try:
        v = float(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be a number (got '{raw}')") from e
    if not lo <= v <= hi:
        raise ConfigError(f"{name} must be between {lo} and {hi}")
    return v


@dataclass
class Config:
    api_key: str = field(default="", repr=False)
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 15.0
    delay: float = 0.5          # seconds between calls; documented limit is 5 per second
    max_retries: int = 2
    max_retry_wait: float = 30.0
    proxies: Optional[Dict[str, str]] = field(default=None, repr=False)

    @classmethod
    def from_env(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        return cls(
            api_key=(env.get("BESTBUY_API_KEY") or "").strip(),
            base_url=(env.get("BESTBUY_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            timeout=_num(env, "SCRAPER_TIMEOUT", 15.0, 1, 120),
            delay=_num(env, "SCRAPER_DELAY", 0.5, 0.25, 60),
            proxies=proxies_from_env(env),
        )

    def require_key(self) -> str:
        if not self.api_key or self.api_key.startswith("YOUR_"):
            raise ConfigError("BESTBUY_API_KEY is not set. Get a key at https://developer.bestbuy.com/ "
                              "and put it in your environment or .env file.")
        return self.api_key
