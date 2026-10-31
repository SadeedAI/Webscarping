# Proxy handoff for Mohamed Samy

Goal: a proxy component that plugs into Shehab's scraper and, when a request is blocked, can supply another route.
It must work for any site (the scraper's site-specific code is only `parser.py`).

## Contract (file: `src/htmlscraper/proxy_iface.py`)
Subclass `ProxyProvider`:
| Method | Called when | You return |
|---|---|---|
| `current()` | before every request | proxy URL (`http://user:pass@host:port`) or `None` (direct) |
| `report_success(proxy)` | request returned 200 | – |
| `report_blocked(proxy, status)` | 403 / 429 on that route | – (e.g. mark proxy as resting) |
| `rotate(reason)` | after a block, only when `--failover` is on | `True` if a different route is now active, `False` if none left |

Rules the scraper enforces (you do not need to): max 2 rotations per URL, max 3 retries, `Retry-After` honoured first,
robots.txt respected, and **it stops when `rotate()` returns `False`**. Never loop inside `rotate()`.
Do not guarantee recovery: a block may be tied to the account, cookies or fingerprint, not the IP.

## Already provided (reference code, tested only with local stubs)
`NoProxy`, `StaticProxy(url)`, `ProxyPool([urls], cooldown)`, and `provider_from_env()`:
`SCRAPER_PROXY_LIST` (comma list) > `SCRAPER_HTTPS_PROXY`/`SCRAPER_HTTP_PROXY` > none. Only `http://`/`https://` URLs; bad values raise `ConfigError`.
Credentials appear in logs as `***:***`. Put real values in your shell or an untracked `.env` only.

## How to integrate
1. Create `src/htmlscraper/my_provider.py` with your class.
2. In `provider_from_env()` (same file as the contract) return it when your env var is set.
3. Run with `--failover`. No change to parser, extractor or transport is needed.

## Configuration contract
| Variable | Meaning | Rules |
|---|---|---|
| `SCRAPER_PROXY_LIST` | comma list of proxy URLs (pool) | checked first |
| `SCRAPER_HTTPS_PROXY` / `SCRAPER_HTTP_PROXY` | one proxy | `http://` or `https://` only |
| (none set) | direct connection | default |
| CLI `--failover` | allow `rotate()` after 403/429 | off by default |
Your own variables are fine. Add them in `provider_from_env()` only.

## Expected behavior (what "correct" looks like)
- 429 with `Retry-After`: scraper waits first. `rotate()` is NOT called for that case.
- 403, or 429 without `Retry-After`: with `--failover`, scraper calls `report_blocked` then `rotate()`. If `True`: it waits (2, 4, 8 s backoff) and retries on the new route. If `False`: it stops and keeps partial results.
- A proxy that fails to connect raises a transport error, which is retried with backoff, then reported as an error.
- Never log passwords. Logs show proxy as `yes/no`; URLs with credentials become `***:***`.

## Acceptance tests
**A. Contract test (offline, run on your provider first):**
```powershell
$env:PYTHONPATH = "src"
$env:SCRAPER_PROVIDER_FACTORY = "htmlscraper.my_provider:make_provider"   # module:function that returns your ProxyProvider
.\.venv\bin\python.exe -m pytest tests/test_provider_contract.py -q
```
Checks: `current()` is None or a valid http(s) URL; report methods never raise; `rotate()` returns a bool and reaches `False` once all routes are blocked; the route changes after `True`; `describe()` hides credentials.
Built-in providers already pass (stubs, no real proxy): `pytest tests/test_html.py tests/test_provider_contract.py -q`.

**B. Live tests.** Mohamed must add and run, with a real authorized proxy and a site that permits it:
1. `.\.venv\bin\python.exe -m htmlscraper.cli --max-pages 1 --out output/proxy_test` with `SCRAPER_HTTP_PROXY` set.
   Pass = exit 0, 6 records, `request_log.csv` column `proxy` = `yes`, and the proxy's own log shows the request.
2. Two-proxy `SCRAPER_PROXY_LIST` where the first is known bad: with `--failover`, log shows one failure then 200.
3. Your provider's `rotate()` returns `False` when all routes are exhausted and the scraper stops.

## Ethics / scope
Use proxies for routing you are authorized to use. Do not use rotation to defeat a site that forbids automated access.

## Status
| Item | Status |
|---|---|
| Interface and reference classes | Done (Shehab) |
| Contract tests, built-in providers | PROXY-INTERFACE, passing |
| Mohamed's provider (`HealthProxyProvider`, env `SCRAPER_MY_PROXY_LIST`) | Done (Mohamed). Typo and indent fixed by Shehab |
| Test A (contract) on Mohamed's provider | Passing, 20/20 |
| Dead proxy (connection refused) | Fixed: `ProxyConnectError`, rotated away from with `--failover`, else retried |
| Wrong proxy password (407) | Fixed: `ProxyAuthError`, never retried on the same proxy; rotated with `--failover` |
| Live test B1-B3 through a local real forward proxy (2026-10-31) | Passing: real proxy 6/6 records; dead-then-good and bad-password-then-good both recover; all-dead stops with exit 1; no password in logs |
| Live test with a third-party (paid) proxy | **NOT TESTED** (none supplied) |
| Failover after a real site block (403/429) | **UNVERIFIED** (only simulated; no real block observed; do not force one) |

Remaining: run test B1 once with a real third-party proxy the team is authorized to use.
