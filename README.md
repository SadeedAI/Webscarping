# HTML Product Scraper with a Pluggable Proxy Interface

Audited and updated 2026-10-29. **Read "Limitations" first.**

## STATUS TABLE (updated 2026-10-29, second pass)
| Item | Category | Status | Evidence |
|---|---|---|---|
| HTML scraping of a real site | **LIVE, verified** | Done | 12 laptop records (webscraper.io) in `output/live/`; 250 country records (scrapethissite.com) in `output/live_scrapethissite/` |
| Site documents a rate limit and bans abusers | **Documented, not observed** | Verified in text only | scrapethissite.com FAQ: max 1 request/second, bans. We ran at 1 request per ~2.5 s |
| Real site actually returned 403/429 to us | **LIVE** | **NOT observed / UNVERIFIED** | Both live logs show only HTTP 200. We did not and will not push a site until it blocks |
| 403 / 429 / Retry-After / backoff handling | **SIMULATED** (local fake site) | Passing | `tests/test_html.py` |
| Parsers on real captured pages | UNIT | Passing | `tests/fixtures/*REAL_captured*` |
| `ProxyProvider` contract + reference classes | **PROXY-INTERFACE** (stub proxies) | Passing | `tests/test_html.py`, `tests/test_provider_contract.py` |
| Real external proxy used by the scraper | **REAL PROXY** | **NOT TESTED** | Needs Mohamed's authorized proxy |
| Real proxy failover after a real block | **REAL PROXY + LIVE** | **NOT TESTED / UNVERIFIED** | Needs both of the above and an authorization to test |
| Scraped site is an e-commerce shop that rate-limits | | **Gap** | No such site found that is both permitted and documented to limit. Approval needed (see below) |

### What each site proves
- **webscraper.io (practice shop):** real product HTML (name, price, rating). Proves the product parser. Proves nothing about blocking.
- **scrapethissite.com (practice site, not a shop):** the only site found that explicitly allows scraping **and** documents a limit and bans. Proves the scraper stays within a documented limit on a real site. It does **not** prove a block was seen or recovered from.
- **Local fake site:** proves our code's reaction to 403/429/5xx. It does not prove any real site behaves that way.
- **Stub proxies:** prove the interface is called correctly. They do not prove a real proxy works.

### Approval / evidence still needed for full compliance
1. Ask the professor in writing: is a documented-limit practice site (scrapethissite.com) acceptable, or must it be a commercial shop?
2. If a shop is required: obtain the site's written permission (or a site that publishes an API/ToS allowing it) before any block test. Newegg and Best Buy HTML were rejected because their rules forbid it.
3. Mohamed's real proxy plus the professor's OK to test failover against an authorized target.

## Website choice: evidence (checked 2026-10-29)
| Site | Finding | Verdict |
|---|---|---|
| **webscraper.io e-commerce test site** | Built for scraping practice. [robots.txt](https://webscraper.io/robots.txt) only disallows `/test-sites/product/`, `/pagination/`, `/scroll/`, `/load-more/`; the path we use (`/test-sites/e-commerce/static/...`) is allowed. Real HTML with schema.org markup. Page text says "for training". No rate limit or terms of use stated. | **Used** |
| Newegg | Real shop with bot protection. [robots.txt](https://www.newegg.com/robots.txt) has `/areyouahuman`. Newegg's [IP-ban help page](https://kb.newegg.com/?p=11668) and terms prohibit automated access and scraping. | **Not used.** It blocks, but scraping is not permitted. |
| Best Buy (HTML) | robots.txt blocks `/api/*.json`, `/browse-api/*`, pricing and availability paths. API terms (50,000/day, 5/s, 403 on excess) apply to the API only. | **Not used** for HTML. API code kept in `bestbuy_scraper/` (needs a key; never run live). |
| **scrapethissite.com** | [FAQ](https://www.scrapethissite.com/faq/) says scraping is allowed; max 1 request/second; identifying User-Agent required; respect robots.txt; temporary or permanent bans. [robots.txt](https://www.scrapethissite.com/robots.txt) disallows only `/lessons/` and `/faq/`; `/pages/simple/` is allowed. Not a shop. Data = countries. | **Used (second site)**. Best match for "documents a rate limit". |
| httpbin.dev / public 429 endpoints | Only mentioned in one blog post; no official documentation of permitted use. | Not used |
| scrapingcourse.com | [robots.txt](https://www.scrapingcourse.com/robots.txt): `Disallow: /ecommerce/*` | Not used |
| books.toscrape.com | Never blocks. Old practice project (`scraper/`). | Kept, not the answer |

I did **not** find a site that is (a) a real shop, (b) permits scraping, and (c) is documented to rate-limit. Hitting a site hard enough to provoke a block, or using a site whose rules forbid scraping, would break the safety rules. So the block behaviour is demonstrated on a local server (below).

## Setup (Windows PowerShell)
The `.venv` was made by MSYS Python: its Python is `.venv\bin\python.exe` (not `Scripts`).
```powershell
cd C:\Users\original\Desktop\scraper_project
.\.venv\bin\python.exe -m pip install -r requirements.txt     # requests, beautifulsoup4, pytest
$env:PYTHONPATH = "src"
```
## Run
```powershell
.\.venv\bin\python.exe -m htmlscraper.cli --max-pages 2 --out output/live    # LIVE, 3 requests, 2 s apart
.\.venv\bin\python.exe -m htmlscraper.cli --site scrapethissite_countries --max-pages 1 --max-records 250 --out output/live_scrapethissite  # LIVE, 2 requests, 2.5 s apart
.\.venv\bin\python.exe -m htmlscraper.cli --failover --out output/live       # allow proxy failover after 403/429
.\.venv\bin\python.exe -m pytest -q                                          # all tests
```
Config (env vars or `.env`, see `.env.example`): `SCRAPER_TIMEOUT` (s, default 15), `SCRAPER_DELAY` (s, min 1, default 2),
`SCRAPER_HTTP_PROXY`, `SCRAPER_HTTPS_PROXY`, `SCRAPER_PROXY_LIST` (comma separated).

## Output example (`output/live/products.csv`, real)
```
name,price,currency,url,description,rating,review_count,category
Packard 255 G2,416.99,USD,https://webscraper.io/test-sites/e-commerce/static/product/31,"15.6"", AMD E2-3800 ...",2,2,laptops
```
Also `products.json` (with `data_origin: LIVE`) and `request_log.csv` (time, url, status, outcome, ms, retry_after, proxy, error).
The site has **no brand or stock field**, so those are not extracted (nothing is invented).

## Architecture
```
cli.py -> extractor.py (follow next links) -> parser.py (HTML -> dicts, pure, site-specific)
                |
                v
        transport.py  HtmlTransport: pacing, robots.txt, timeouts, backoff, Retry-After, key/credential redaction
                |  asks
                v
        proxy_iface.py  ProxyProvider (contract)  <-- Mohamed implements / configures
                         NoProxy | StaticProxy | ProxyPool (reference code)
```
**Shehab owns:** parser, extractor, transport, retry policy, tests, docs. **Mohamed owns:** real proxy provider(s). See `HANDOFF_PROXY_MOHAMED.md`.

## Error handling (implemented in `transport.py`)
| Event | Behaviour |
|---|---|
| robots.txt disallows | not fetched (`ForbiddenError`) |
| 429 + usable `Retry-After` (≤ 60 s) | wait exactly that, retry; max 3 retries |
| 429 without it / 403 | no same-route retry. If `--failover` AND the provider has another route: rotate (max 2), else **stop** |
| 5xx, timeout, connection error | exponential backoff 2, 4, 8 s (jitter on), max 3 retries |
| 200 but not a product page | `MalformedResponse`; results so far are kept |
A proxy only changes the route. It does not guarantee recovery, and failover is off by default. Use it only where the site's rules allow.

## Test results (run 2026-10-29): `pytest -q` = **89 passed, 0 failed**
Adding a site = one parser in `sites.py` (see registry). Categories:
- **LIVE (webscraper.io):** 1 run, 3 requests (robots + 2 pages), all HTTP 200, 12 records. No block seen.
- **LIVE (scrapethissite.com):** 1 run, 2 requests (robots + 1 page), 2.5 s apart (limit is 1/s), HTTP 200, 250 records. No block seen. (`products.csv` here holds countries.)
- **UNIT on a real captured page** (`tests/fixtures/laptops_page1_REAL_captured_2026-10-29.html`): parser.
- **SIMULATED local site** (`htmlscraper/sim_site.py`): 429 + Retry-After, 403, 500 backoff, timeout, robots, partial results.
- **PROXY-IFACE with local stub proxies:** routing, failover, cooldown, config validation, credential redaction.
- **Real external proxy:** NOT TESTED.

## Limitations
- The only real site used does not block, so no real block was observed.
- Simulated blocks prove our code's reaction, not that any real site would behave that way.
- The target is a practice site. Reusing the parser elsewhere needs a new `parse_listing`.
- Best Buy API code needs a key and was never run live. Newegg was researched only, never fetched except robots.txt.

## Troubleshooting
- `ModuleNotFoundError` -> `$env:PYTHONPATH="src"`.
- `CONFIG ERROR` -> check proxy URL format `http://user:pass@host:port`.
- Exit 1 and `stopped_with` set -> read `output/live/request_log.csv`.
Test Contributors:
- Mohamed Koura

