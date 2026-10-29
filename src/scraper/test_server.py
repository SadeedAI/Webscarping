"""Local SIMULATED rate-limit server. Returns 200 until LIMIT requests per WINDOW seconds, then 429.

Run: python -m scraper.test_server --limit 5 --window 10 --port 8099
Also: /forbidden -> 403, /error -> 500, /slow -> 200 after 3s.
"""
import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_server(limit: int = 5, window: float = 10.0, port: int = 0, host: str = "127.0.0.1"):
    state = {"hits": [], "lock": threading.Lock()}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body="", extra=None):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/forbidden":
                return self._send(403, "forbidden")
            if self.path == "/error":
                return self._send(500, "boom")
            if self.path == "/slow":
                time.sleep(3)
                return self._send(200, "slow")
            now = time.monotonic()
            with state["lock"]:
                state["hits"] = [t for t in state["hits"] if now - t < window]
                used = len(state["hits"])
                if used >= limit:
                    retry = max(1, int(window - (now - state["hits"][0]) + 0.999))
                    return self._send(429, "too many requests", {
                        "Retry-After": str(retry), "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0"})
                state["hits"].append(now)
                remaining = limit - used - 1
            self._send(200, "ok", {"X-RateLimit-Limit": str(limit),
                                   "X-RateLimit-Remaining": str(remaining)})

    return ThreadingHTTPServer((host, port), H)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--window", type=float, default=10)
    ap.add_argument("--port", type=int, default=8099)
    a = ap.parse_args()
    srv = make_server(a.limit, a.window, a.port)
    print(f"Test server on http://127.0.0.1:{a.port} limit={a.limit}/{a.window}s")
    srv.serve_forever()
