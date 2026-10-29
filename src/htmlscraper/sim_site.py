"""SIMULATED shop for tests. NOT a real site. It serves a REAL captured HTML page as its body,
but the blocking behaviour is invented by this file. Evidence from it is "SIMULATED" only.

Behaviours (`mode`): "ok", "429" (after `limit` hits, with Retry-After), "403" (after `limit` hits).
Also serves /robots.txt (configurable) and /boom (500).
"""
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures",
                       "laptops_page1_REAL_captured_2026-10-29.html")
PATH = "/test-sites/e-commerce/static/computers/laptops"


def make_site(mode="ok", limit=2, retry_after=1, robots="User-agent: *\nDisallow: /nothing/\n", port=0,
              fixture=FIXTURE, path=PATH):
    html = open(fixture, "rb").read()
    PATH_ = path
    st = {"hits": 0, "lock": threading.Lock(), "log": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body=b"", ctype="text/html", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            st["log"].append(self.path)
            if path == "/robots.txt":
                return self._send(200, robots.encode(), "text/plain")
            if path == "/boom":
                return self._send(500, b"boom")
            if path != PATH_:
                return self._send(404, b"nf")
            with st["lock"]:
                st["hits"] += 1
                n = st["hits"]
            if mode == "429" and n > limit:
                return self._send(429, b"slow down", extra={"Retry-After": str(retry_after)})
            if mode == "403" and n > limit:
                return self._send(403, b"forbidden")
            return self._send(200, html)

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.state = st
    return srv


def start(**kw):
    srv = make_site(**kw)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"
