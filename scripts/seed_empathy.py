"""Insert the empathy-flow documents that are not already in Atlas.

Reads MONGODB_URI from the environment. Does not print the URI, and does not
delete or overwrite documents that are already there.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from pymongo import MongoClient


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=timezone.utc)


ORDERS = {
    "BLY-22044": {
        "_id": "BLY-22044",
        "customerId": "cust_becky",
        "placedAt": _utc(2026, 9, 30, 15, 0),
        "deliveredAt": _utc(2026, 10, 1, 18, 0),
        "status": "delivered",
        "genre": "horror",
        "lines": [
            {
                "sku": "9780525620785",
                "title": "Mexican Gothic",
                "qty": 1,
                "unitPriceCents": 1699,
                "genre": "horror",
            }
        ],
        "shippingCents": 0,
        "totalCents": 1699,
        "refundableCents": 1699,
        "paymentMethodId": "pm_becky_visa",
        "syncedAt": _utc(2026, 10, 2, 12, 0),
    },
    "BLY-33010": {
        "_id": "BLY-33010",
        "customerId": "cust_bob",
        "placedAt": _utc(2026, 9, 12, 11, 0),
        "deliveredAt": _utc(2026, 9, 28, 18, 0),
        "neededBy": _utc(2026, 9, 20, 0, 0),
        "status": "delivered",
        "deliveredLate": True,
        "gift": "birthday",
        "genre": "fiction",
        "lines": [
            {
                "sku": "9780670026197",
                "title": "A Gentleman in Moscow",
                "qty": 1,
                "unitPriceCents": 1800,
                "genre": "fiction",
            }
        ],
        "shippingCents": 0,
        "totalCents": 1800,
        "refundableCents": 1800,
        "paymentMethodId": "pm_bob_visa",
        "syncedAt": _utc(2026, 10, 2, 12, 0),
    },
}

CUSTOMERS = {
    "cust_bob": {
        "_id": "cust_bob",
        "email": "bob@example.com",
        "name": "Bob Hale",
        "authSubject": "bookly|bob",
    }
}

PAYMENTS = {
    "pm_bob_visa": {
        "_id": "pm_bob_visa",
        "customerId": "cust_bob",
        "brand": "Visa",
        "last4": "1881",
        "expMonth": 3,
        "expYear": 2029,
        "processor": "stripe",
        "processorPaymentMethodId": "pm_seed_visa_1881",
    }
}

CATALOG = {
    "book_piranesi": {
        "_id": "book_piranesi",
        "title": "Piranesi",
        "genre": "fantasy",
        "author": "Susanna Clarke",
    },
    "book_hail_mary": {
        "_id": "book_hail_mary",
        "title": "Project Hail Mary",
        "genre": "science fiction",
        "author": "Andy Weir",
    },
    "book_cerulean": {
        "_id": "book_cerulean",
        "title": "The House in the Cerulean Sea",
        "genre": "fantasy",
        "author": "TJ Klune",
    },
    "book_hill_house": {
        "_id": "book_hill_house",
        "title": "The Haunting of Hill House",
        "genre": "horror",
        "author": "Shirley Jackson",
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
    database.discounts.create_index(
        [("customerId", 1), ("orderId", 1)],
        unique=True,
        name="uniq_customer_order_discount",
    )
    print("discount index ready")
    _insert_missing(database.customers, CUSTOMERS)
    _insert_missing(database.paymentMethods, PAYMENTS)
    _insert_missing(database.orders, ORDERS)
    _insert_missing(database.catalog, CATALOG)
    completed_returns = database.returns.count_documents({"orderId": "BLY-22018", "status": "completed"})
    print(f"BLY-22018 completed returns: {completed_returns}")
    client.close()


if __name__ == "__main__":
    main()
