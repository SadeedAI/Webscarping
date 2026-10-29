"""Pure parsing: Best Buy Products API JSON -> flat records. No network, no secrets."""
from typing import Any, Dict, List, Tuple

from .errors import MalformedResponse

# Fields requested from the API (the `show=` parameter).
API_FIELDS = ["sku", "name", "manufacturer", "regularPrice", "salePrice", "url",
              "onlineAvailability", "inStoreAvailability", "categoryPath", "modelNumber"]

RECORD_FIELDS = ["product_id", "name", "brand", "regular_price", "sale_price",
                 "category", "url", "online_available", "in_store_available", "model_number"]


def parse_product(p: Dict[str, Any]) -> Dict[str, Any]:
    """Return a record with only keys the API actually returned (missing -> None)."""
    if not isinstance(p, dict) or p.get("sku") is None:
        raise MalformedResponse("product entry without a sku")
    path = p.get("categoryPath")
    category = None
    if isinstance(path, list) and path:
        names = [c.get("name") for c in path if isinstance(c, dict) and c.get("name")]
        category = " > ".join(names) or None
    return {
        "product_id": p.get("sku"),
        "name": p.get("name"),
        "brand": p.get("manufacturer"),
        "regular_price": p.get("regularPrice"),
        "sale_price": p.get("salePrice"),
        "category": category,
        "url": p.get("url"),
        "online_available": p.get("onlineAvailability"),
        "in_store_available": p.get("inStoreAvailability"),
        "model_number": p.get("modelNumber"),
    }


def parse_page(payload: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Parse one page of /products results. Bad entries are skipped and counted."""
    if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
        raise MalformedResponse("response has no 'products' list")
    records, skipped = [], 0
    for item in payload["products"]:
        try:
            records.append(parse_product(item))
        except MalformedResponse:
            skipped += 1
    meta = {
        "current_page": payload.get("currentPage"),
        "total_pages": payload.get("totalPages"),
        "total": payload.get("total"),
        "skipped": skipped,
    }
    return records, meta
