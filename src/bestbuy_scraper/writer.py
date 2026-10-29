"""Output writing: CSV, JSON, and the request log."""
import csv
import json
import os
import time

from .parser import RECORD_FIELDS


def write_outputs(records, out_dir, query, summary=None):
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "bestbuy_products.csv")
    json_path = os.path.join(out_dir, "bestbuy_products.json")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RECORD_FIELDS)
        w.writeheader()
        w.writerows(records)
    doc = {
        "source": "Best Buy Products API (https://api.bestbuy.com/v1)",
        "query": query,
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "note": "Best Buy terms allow caching only temporarily (72 hours). Refresh or delete after that.",
        "summary": summary or {},
        "count": len(records),
        "products": records,
    }
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
    return csv_path, json_path


def write_request_log(events, path):
    """CSV of every HTTP attempt. URLs are already redacted by the transport."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cols = ["time", "url", "status", "outcome", "ms", "retry-after", "x-ratelimit-remaining", "error"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for e in events:
            h = e.get("headers", {})
            w.writerow([e["time"], e["url"], e["status"], e["outcome"], e["ms"],
                        h.get("retry-after", ""), h.get("x-ratelimit-remaining", ""), e["error"]])
