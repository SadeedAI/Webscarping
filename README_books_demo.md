# Books Scraper (proxy-ready)

Scrapes book data from https://books.toscrape.com (a sandbox site built for scraping practice; no robots.txt, HTTP 404 checked on 2026-10-28).
Rate limits are tested against a **local simulated server**, not a real website.

## Setup (Windows PowerShell)
```powershell
python -m venv .venv
.\.venv\bin\python.exe -m pip install -r requirements.txt   # on a normal Windows Python use .\.venv\Scripts\python.exe
$env:PYTHONPATH = "src"
```

## Run
```powershell
python -m scraper.cli --pages 3 --details --delay 1 --out output   # real scrape -> output/books.csv + books.json
python -m scraper.ratelimit_test                                    # simulated 429 test -> output/ratelimit_log.csv
python -m pytest -v                                                 # 9 automated tests
```
Options: `--timeout` (s), `--delay` (s between requests), `--pages`, `--details` (also fetch each book page for its category).

## Architecture
```
cli.py (retry, save) -> parser.py (pure HTML -> dicts, no network)
        |
        v
transport.py  HttpTransport  <-- ONLY place that knows about proxies
        |  (SCRAPER_HTTP_PROXY / SCRAPER_HTTPS_PROXY)
        v
   [optional proxy layer by Mohamed] -> target site
```
Swap or extend `HttpTransport` and the parser does not change.

## Proxy config (optional)
Copy `.env.example`, set `SCRAPER_HTTP_PROXY=http://user:password@host:port` in your shell environment.
Unset = direct connection. System proxy variables are ignored on purpose (`trust_env=False`).

## HTTP status meanings
- **429** Too Many Requests: you hit a rate limit. Wait for `Retry-After`. The scraper does this (max 30s, 2 retries).
- **403** Forbidden: server refuses you. Not always a rate limit. Not retried.
- **5xx**: server fault. Not retried.
- **Timeout / connection refused**: no HTTP answer at all. Raised as `TransportError`, retried twice.

## Troubleshooting
- `ModuleNotFoundError: scraper` -> set `$env:PYTHONPATH="src"`.
- Empty output -> check the log; the CLI exits with code 1 and saves nothing if no data came back.
