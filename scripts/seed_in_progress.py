"""Upsert orders that are still being sent. Does not touch delivered orders.

Reads MONGODB_URI from the environment. Does not print the URI. Does not delete
customers, returns, discounts, sessions, or the delivered orders already on file.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from pymongo import MongoClient

PROTECTED = ("BLY-22018", "BLY-22002", "BLY-22044", "BLY-33010")


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=timezone.utc)


def _order(
    order_id: str,
    customer_id: str,
    payment_method_id: str,
    title: str,
    sku: str,
    genre: str,
    cents: int,
    status: str,
    detail: str,
    hour: int,
) -> dict:
    return {
        "_id": order_id,
        "customerId": customer_id,
        "placedAt": _utc(2026, 10, 1, hour),
        "status": status,
        "statusDetail": detail,
        "genre": genre,
        "lines": [
            {
                "sku": sku,
                "title": title,
                "qty": 1,
                "unitPriceCents": cents,
                "genre": genre,
            }
        ],
        "shippingCents": 0,
        "totalCents": cents,
        "refundableCents": cents,
        "paymentMethodId": payment_method_id,
        "syncedAt": _utc(2026, 10, 2, 12),
    }


ORDERS = {
    "BLY-44120": _order(
        "BLY-44120",
        "cust_becky",
        "pm_becky_visa",
        "Klara and the Sun",
        "9780593318171",
        "fiction",
        1700,
        "packing",
        "It is being packed at the Bookly warehouse.",
        14,
    ),
    "BLY-44121": _order(
        "BLY-44121",
        "cust_becky",
        "pm_becky_visa",
        "The Night Circus",
        "9780307744432",
        "fantasy",
        1699,
        "shipped",
        "It left the Bookly warehouse this morning.",
        16,
    ),
    "BLY-44122": _order(
        "BLY-44122",
        "cust_bob",
        "pm_bob_visa",
        "Educated",
        "9780399590504",
        "memoir",
        1800,
        "on the way",
        "It is on a truck between the warehouse and Memphis.",
        13,
    ),
    "BLY-44123": _order(
        "BLY-44123",
        "cust_bob",
        "pm_bob_visa",
        "Beach Read",
        "9781984806734",
        "romance",
        1600,
        "out for delivery",
        "A driver has it on the route today in Memphis.",
        17,
    ),
}


def _counts(database) -> str:
    return (
        f"customers={database.customers.count_documents({})} "
        f"orders={database.orders.count_documents({})} "
        f"returns={database.returns.count_documents({})} "
        f"discounts={database.discounts.count_documents({})} "
        f"sessions={database.sessions.count_documents({})}"
    )


def main() -> None:
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        raise SystemExit("MONGODB_URI is not set")
    overlap = set(ORDERS) & set(PROTECTED)
    if overlap:
        raise SystemExit("refusing to rewrite a delivered order")
    client = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=12000, appname="bookly-seed")
    database = client["bookly"]
    print("before " + _counts(database))
    for order_id, document in ORDERS.items():
        fields = {key: value for key, value in document.items() if key != "_id"}
        result = database.orders.update_one(
            {"_id": order_id},
            {"$set": fields, "$unset": {"deliveredAt": "", "deliveredLate": ""}},
            upsert=True,
        )
        if result.upserted_id is not None:
            print(f"inserted {order_id}")
        else:
            print(f"updated {order_id}")
    for order_id in (*PROTECTED, *ORDERS):
        document = database.orders.find_one(
            {"_id": order_id},
            {"customerId": 1, "status": 1, "statusDetail": 1, "deliveredAt": 1, "deliveredLate": 1, "lines.title": 1},
        )
        if document is None:
            print(f"missing {order_id}")
            continue
        titles = [line.get("title") for line in document.get("lines") or []]
        late = "deliveredLate" in document
        delivered = "deliveredAt" in document
        print(
            order_id,
            document.get("customerId"),
            document.get("status"),
            titles,
            "has-deliveredAt" if delivered else "no-deliveredAt",
            "has-deliveredLate" if late else "no-deliveredLate",
        )
    print("after " + _counts(database))
    client.close()


if __name__ == "__main__":
    main()
