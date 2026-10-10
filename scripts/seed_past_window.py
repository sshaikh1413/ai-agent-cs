"""Upsert Becky's older delivered order and her shipping address.

Reads MONGODB_URI from the environment. Does not print the URI. Does not delete
customers, catalog rows, in-progress orders, or in-window delivered orders.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from pymongo import MongoClient

ORDER_ID = "BLY-18440"
TITLE = "Piranesi"
WATCH = (
    "BLY-22018",
    "BLY-22002",
    "BLY-22044",
    "BLY-33010",
    "BLY-44120",
    "BLY-44121",
    "BLY-44122",
    "BLY-44123",
)
ADDRESS = {
    "line1": "418 Linden Street",
    "city": "Oakland",
    "region": "CA",
    "postalCode": "94607",
}


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=timezone.utc)


ORDER = {
    "_id": ORDER_ID,
    "customerId": "cust_becky",
    "placedAt": _utc(2026, 8, 10, 15, 0),
    "deliveredAt": _utc(2026, 8, 15, 18, 0),
    "status": "delivered",
    "genre": "fantasy",
    "lines": [
        {
            "sku": "9781635575637",
            "title": TITLE,
            "qty": 1,
            "unitPriceCents": 1599,
            "genre": "fantasy",
        }
    ],
    "shippingCents": 0,
    "totalCents": 1599,
    "refundableCents": 1599,
    "paymentMethodId": "pm_becky_visa",
    "syncedAt": _utc(2026, 10, 2, 12, 0),
}

CATALOG = {
    "_id": "book_piranesi",
    "title": TITLE,
    "genre": "fantasy",
    "author": "Susanna Clarke",
    "summary": "A man records the tides in a house of statues.",
}


def _dump(document: dict | None) -> str:
    if document is None:
        return ""
    return str(sorted((key, str(value)) for key, value in document.items()))


def _watch(database) -> dict[str, str]:
    found: dict[str, str] = {}
    for order_id in WATCH:
        found[order_id] = _dump(database.orders.find_one({"_id": order_id}))
    return found


def _becky_without_address(database) -> str:
    document = database.customers.find_one({"_id": "cust_becky"})
    if document is None:
        return ""
    kept = {key: value for key, value in document.items() if key != "shippingAddress"}
    return _dump(kept)


def main() -> None:
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        raise SystemExit("MONGODB_URI is not set")
    client = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=12000, appname="bookly-seed")
    database = client["bookly"]
    before = _watch(database)
    becky_before = _becky_without_address(database)
    if not becky_before:
        raise SystemExit("cust_becky is not on file")
    existing = database.orders.find_one({"_id": ORDER_ID}, {"customerId": 1})
    if existing is not None and existing.get("customerId") != "cust_becky":
        raise SystemExit("order id belongs to another customer")

    fields = {key: value for key, value in ORDER.items() if key != "_id"}
    result = database.orders.update_one({"_id": ORDER_ID}, {"$set": fields}, upsert=True)
    if result.upserted_id is not None:
        print(f"inserted {ORDER_ID} {TITLE}")
    else:
        print(f"updated {ORDER_ID} {TITLE}")

    database.customers.update_one(
        {"_id": "cust_becky"},
        {"$set": {"shippingAddress": ADDRESS}},
    )
    print("shipping address set on cust_becky")

    catalog = database.catalog.find_one({"_id": CATALOG["_id"]}, {"author": 1, "summary": 1, "title": 1})
    author = catalog.get("author") if catalog else None
    summary = catalog.get("summary") if catalog else None
    if catalog is None or not (isinstance(author, str) and author.strip() and isinstance(summary, str) and summary.strip()):
        database.catalog.update_one({"_id": CATALOG["_id"]}, {"$set": CATALOG}, upsert=True)
        print("catalog filled for Piranesi")
    else:
        print("catalog already has Piranesi")

    after = _watch(database)
    changed = [order_id for order_id in WATCH if before[order_id] != after[order_id]]
    if changed:
        raise SystemExit("refusing watched order change: " + ", ".join(changed))
    if _becky_without_address(database) != becky_before:
        raise SystemExit("customer fields other than the address changed")
    stored = database.orders.find_one({"_id": ORDER_ID}, {"status": 1, "deliveredAt": 1, "lines.title": 1})
    print(f"status={stored.get('status')} deliveredAt={stored.get('deliveredAt')} title={TITLE}")
    client.close()


if __name__ == "__main__":
    main()
