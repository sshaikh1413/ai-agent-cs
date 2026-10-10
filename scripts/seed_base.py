"""Insert the starting records the other seed scripts build on.

Run this first on an empty `bookly` database. It adds Becky's customer record,
her card, her two in-window delivered orders, and the 30-day return-window
policy. Order dates are counted back from today, so a fresh desk always has
books inside the return window.

Reads MONGODB_URI from the environment. Does not print the URI, and does not
delete or overwrite documents that are already there.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient


def _days_ago(days: int, now: datetime) -> datetime:
    return (now - timedelta(days=days)).replace(microsecond=0)


def customers() -> dict[str, dict]:
    return {
        "cust_becky": {
            "_id": "cust_becky",
            "email": "becky@example.com",
            "name": "Becky Alvarez",
            "authSubject": "bookly|becky",
            "shippingAddress": {
                "line1": "418 Linden Street",
                "city": "Oakland",
                "region": "CA",
                "postalCode": "94607",
            },
        },
    }


def payments() -> dict[str, dict]:
    return {
        "pm_becky_visa": {
            "_id": "pm_becky_visa",
            "customerId": "cust_becky",
            "brand": "Visa",
            "last4": "4242",
            "expMonth": 8,
            "expYear": 2028,
            "processor": "stripe",
            "processorPaymentMethodId": "pm_seed_visa_4242",
        },
    }


def orders(now: datetime) -> dict[str, dict]:
    """The Midnight Library was ordered about a week ago; Circe about three weeks ago."""

    return {
        "BLY-22018": {
            "_id": "BLY-22018",
            "customerId": "cust_becky",
            "placedAt": _days_ago(7, now),
            "deliveredAt": _days_ago(5, now),
            "status": "delivered",
            "lines": [{"sku": "9780525559474", "title": "The Midnight Library", "qty": 1, "unitPriceCents": 1699}],
            "shippingCents": 595,
            "totalCents": 2294,
            "refundableCents": 1699,
            "paymentMethodId": "pm_becky_visa",
            "syncedAt": now.replace(microsecond=0),
        },
        "BLY-22002": {
            "_id": "BLY-22002",
            "customerId": "cust_becky",
            "placedAt": _days_ago(20, now),
            "deliveredAt": _days_ago(16, now),
            "status": "delivered",
            "lines": [{"sku": "9780316556347", "title": "Circe", "qty": 1, "unitPriceCents": 1700}],
            "shippingCents": 0,
            "totalCents": 1700,
            "refundableCents": 1700,
            "paymentMethodId": "pm_becky_visa",
            "syncedAt": now.replace(microsecond=0),
        },
    }


POLICIES = {
    "return-window": {
        "_id": "return-window",
        "returnWindowDays": 30,
        "version": 1,
        "body": (
            "Delivered books can be returned within 30 days for a refund to the "
            "original payment method or for store credit."
        ),
    },
}


def _insert_missing(collection, documents: dict[str, dict]) -> None:
    for document_id, document in documents.items():
        found = collection.find_one({"_id": document_id}, {"_id": 1})
        if found is None:
            collection.insert_one(document)
            print(f"inserted {document_id}")
        else:
            print(f"already present {document_id}")


def main() -> None:
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        raise SystemExit("MONGODB_URI is not set")
    client = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=12000, appname="bookly-seed")
    database = client["bookly"]
    now = datetime.now(timezone.utc)
    _insert_missing(database.customers, customers())
    _insert_missing(database.paymentMethods, payments())
    _insert_missing(database.orders, orders(now))
    _insert_missing(database.policies, POLICIES)
    print(
        "after "
        f"customers={database.customers.count_documents({})} "
        f"orders={database.orders.count_documents({})} "
        f"policies={database.policies.count_documents({})}"
    )
    client.close()


if __name__ == "__main__":
    main()
