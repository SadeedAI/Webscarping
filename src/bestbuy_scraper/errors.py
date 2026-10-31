"""Typed errors so callers can tell HTTP outcomes apart."""


class ScraperError(Exception):
    """Base class."""


class ConfigError(ScraperError):
    """Bad or missing configuration (key, proxy, numbers)."""


class TransportError(ScraperError):
    """No HTTP answer: timeout or connection failure."""


class ProxyConnectError(TransportError):
    """The proxy itself could not be reached. With failover on, the route is switched."""


class ProxyAuthError(ProxyConnectError):
    """The proxy rejected its credentials (407). Retrying the same proxy cannot help."""


class HttpStatusError(ScraperError):
    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class AuthError(HttpStatusError):
    """401, or 403 with an invalid/missing key message."""


class QuotaExhausted(HttpStatusError):
    """403 whose message says the call limit was exceeded (Best Buy uses 403, not 429)."""


class ForbiddenError(HttpStatusError):
    """403 with no clear reason. Never retried."""


class RateLimitError(HttpStatusError):
    """429. Retried only as far as Retry-After allows."""


class ServerError(HttpStatusError):
    """5xx."""


class ClientError(HttpStatusError):
    """Other 4xx (400, 404, ...)."""


class MalformedResponse(ScraperError):
    """Body was not the JSON shape we expect."""
