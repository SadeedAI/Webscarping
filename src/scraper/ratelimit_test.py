"""Repeatable rate-limit test against the LOCAL SIMULATED server.

Run: python -m scraper.ratelimit_test
Writes output/ratelimit_log.csv. Results are SIMULATED, not from a real website.
"""
import csv
import os
import threading
import time

from .test_server import make_server
from .transport import HttpTransport, TransportError

LIMIT, WINDOW, TOTAL = 5, 6.0, 8


def classify(status: int) -> str:
    if status == 429:
        return "RATE_LIMITED (429)"
    if status == 403:
        return "FORBIDDEN (403) - access denied, not necessarily rate limit"
    if status >= 500:
        return "SERVER_ERROR"
    return "OK" if status < 400 else "CLIENT_ERROR"


def run(outdir: str = "output") -> list:
    srv = make_server(LIMIT, WINDOW)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tp = HttpTransport(timeout=5, delay=0.2)
    rows = []
    base = f"http://127.0.0.1:{port}"
    for i in range(1, TOTAL + 1):
        r = tp.get(base + "/")
        rows.append({"n": i, "time": time.strftime("%H:%M:%S"), "status": r.status,
                     "ms": round(r.elapsed * 1000, 1), "class": classify(r.status), **r.headers})
    time.sleep(WINDOW + 0.5)  # wait for the window to reset
    r = tp.get(base + "/")
    rows.append({"n": TOTAL + 1, "time": time.strftime("%H:%M:%S"), "status": r.status,
                 "ms": round(r.elapsed * 1000, 1), "class": classify(r.status) + " after reset", **r.headers})
    for path in ("/forbidden", "/error"):
        r = tp.get(base + path)
        rows.append({"n": path, "time": time.strftime("%H:%M:%S"), "status": r.status,
                     "ms": round(r.elapsed * 1000, 1), "class": classify(r.status)})
    try:
        HttpTransport(timeout=1, delay=0).get(base + "/slow")
    except TransportError as e:
        rows.append({"n": "/slow", "time": time.strftime("%H:%M:%S"), "status": "", "ms": "",
                     "class": f"CONNECTION_ERROR (timeout): {e}"})
    srv.shutdown()

    os.makedirs(outdir, exist_ok=True)
    cols = ["n", "time", "status", "ms", "class", "retry-after", "x-ratelimit-limit", "x-ratelimit-remaining"]
    with open(os.path.join(outdir, "ratelimit_log.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(rows)
    for row in rows:
        print(row)
    return rows


if __name__ == "__main__":
    run()
