"""SIMULATED Best Buy-shaped API for tests. NOT Best Buy. Data here is fake fixture data.

Modes (set per path prefix):
  /v1/products(...)   -> 200 JSON pages until `limit` calls, then `over` behaviour
  /forbidden          -> 403 invalid key message
  /error              -> 500
  /slow               -> 200 after 3 seconds
  /badjson            -> 200 with non-JSON body
Over-limit behaviour: "429" (with Retry-After) or "403" (Best Buy's documented style).
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def fake_product(i):
    return {"sku": 1000 + i, "name": f"FIXTURE product {i}", "manufacturer": "FixtureBrand",
            "regularPrice": 100.0 + i, "salePrice": 90.0 + i, "url": f"https://example.invalid/p/{i}",
            "onlineAvailability": True, "inStoreAvailability": False,
            "categoryPath": [{"id": "a", "name": "Home"}, {"id": "b", "name": "Laptops"}],
            "modelNumber": f"M{i}"}


def make_server(limit=1000, over="429", retry_after=1, total=60, port=0):
    state = {"calls": 0, "lock": threading.Lock()}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json", extra=None):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/forbidden":
                return self._send(403, json.dumps({"error": {"code": 403, "message": "Invalid API key"}}))
            if u.path == "/error":
                return self._send(500, "boom", "text/plain")
            if u.path == "/slow":
                time.sleep(3)
                return self._send(200, "{}")
            if u.path == "/badjson":
                return self._send(200, "<html>not json</html>", "text/html")
            with state["lock"]:
                state["calls"] += 1
                n = state["calls"]
            if n > limit:
                if over == "429":
                    return self._send(429, json.dumps({"error": "too many requests"}),
                                      extra={"Retry-After": str(retry_after)})
                return self._send(403, json.dumps({"error": {"code": 403,
                                  "message": "Over quota: call limit exceeded"}}))
            q = parse_qs(u.query)
            size = int(q.get("pageSize", ["10"])[0])
            page = int(q.get("page", ["1"])[0])
            start = (page - 1) * size
            items = [fake_product(i) for i in range(start, min(start + size, total))]
            pages = -(-total // size)
            self._send(200, json.dumps({"currentPage": page, "totalPages": pages,
                                        "total": total, "products": items}))

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    srv.state = state
    return srv


def start_in_thread(**kw):
    srv = make_server(**kw)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"
