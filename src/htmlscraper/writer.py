"""CSV / JSON / request-log output."""
import csv
import json
import os
import time

from .parser import FIELDS


def write_products(records, out_dir, source_url, summary, label="LIVE", fields=FIELDS):
    os.makedirs(out_dir, exist_ok=True)
    c, j = os.path.join(out_dir, "products.csv"), os.path.join(out_dir, "products.json")
    with open(c, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(records)
    with open(j, "w", encoding="utf-8") as fh:
        json.dump({"data_origin": label, "source": source_url,
                   "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                   "summary": summary, "count": len(records), "products": records},
                  fh, indent=2, ensure_ascii=False)
    return c, j


def write_request_log(events, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    cols = ["time", "url", "status", "outcome", "ms", "retry_after", "proxy", "error"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for e in events:
            w.writerow({k: e.get(k, "") for k in cols})
