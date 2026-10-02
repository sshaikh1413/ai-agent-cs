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

# Titles and genres only. No book text. These are written into Atlas; the desk
# does not look them up on the web. Upsert sets title and genre and leaves
# every other field on an existing row alone.
CATALOG = {
    "book_piranesi": {"_id": "book_piranesi", "title": "Piranesi", "genre": "fantasy"},
    "book_hail_mary": {"_id": "book_hail_mary", "title": "Project Hail Mary", "genre": "science fiction"},
    "book_cerulean": {"_id": "book_cerulean", "title": "The House in the Cerulean Sea", "genre": "fantasy"},
    "book_hill_house": {"_id": "book_hill_house", "title": "The Haunting of Hill House", "genre": "horror"},
    "book_dracula": {"_id": "book_dracula", "title": "Dracula", "genre": "horror"},
    "book_frankenstein": {"_id": "book_frankenstein", "title": "Frankenstein", "genre": "horror"},
    "book_the_shining": {"_id": "book_the_shining", "title": "The Shining", "genre": "horror"},
    "book_carrie": {"_id": "book_carrie", "title": "Carrie", "genre": "horror"},
    "book_pet_sematary": {"_id": "book_pet_sematary", "title": "Pet Sematary", "genre": "horror"},
    "book_mexican_gothic": {"_id": "book_mexican_gothic", "title": "Mexican Gothic", "genre": "horror"},
    "book_midnight_library": {"_id": "book_midnight_library", "title": "The Midnight Library", "genre": "fiction"},
    "book_circe": {"_id": "book_circe", "title": "Circe", "genre": "fiction"},
    "book_gentleman": {"_id": "book_gentleman", "title": "A Gentleman in Moscow", "genre": "fiction"},
    "book_klara": {"_id": "book_klara", "title": "Klara and the Sun", "genre": "fiction"},
    "book_remains": {"_id": "book_remains", "title": "The Remains of the Day", "genre": "fiction"},
    "book_beloved": {"_id": "book_beloved", "title": "Beloved", "genre": "fiction"},
    "book_normal_people": {"_id": "book_normal_people", "title": "Normal People", "genre": "fiction"},
    "book_night_circus": {"_id": "book_night_circus", "title": "The Night Circus", "genre": "fantasy"},
    "book_addie": {"_id": "book_addie", "title": "The Invisible Life of Addie LaRue", "genre": "fantasy"},
    "book_name_of_the_wind": {"_id": "book_name_of_the_wind", "title": "The Name of the Wind", "genre": "fantasy"},
    "book_dune": {"_id": "book_dune", "title": "Dune", "genre": "science fiction"},
    "book_left_hand": {"_id": "book_left_hand", "title": "The Left Hand of Darkness", "genre": "science fiction"},
    "book_station_eleven": {"_id": "book_station_eleven", "title": "Station Eleven", "genre": "science fiction"},
    "book_the_martian": {"_id": "book_the_martian", "title": "The Martian", "genre": "science fiction"},
    "book_thursday": {"_id": "book_thursday", "title": "The Thursday Murder Club", "genre": "mystery"},
    "book_gone_girl": {"_id": "book_gone_girl", "title": "Gone Girl", "genre": "mystery"},
    "book_silent_patient": {"_id": "book_silent_patient", "title": "The Silent Patient", "genre": "mystery"},
    "book_and_then": {"_id": "book_and_then", "title": "And Then There Were None", "genre": "mystery"},
    "book_pride": {"_id": "book_pride", "title": "Pride and Prejudice", "genre": "romance"},
    "book_evelyn": {"_id": "book_evelyn", "title": "The Seven Husbands of Evelyn Hugo", "genre": "romance"},
    "book_beach_read": {"_id": "book_beach_read", "title": "Beach Read", "genre": "romance"},
    "book_red_white": {"_id": "book_red_white", "title": "Red, White & Royal Blue", "genre": "romance"},
    "book_educated": {"_id": "book_educated", "title": "Educated", "genre": "memoir"},
    "book_becoming": {"_id": "book_becoming", "title": "Becoming", "genre": "memoir"},
    "book_born_a_crime": {"_id": "book_born_a_crime", "title": "Born a Crime", "genre": "memoir"},
    "book_sapiens": {"_id": "book_sapiens", "title": "Sapiens", "genre": "history"},
    "book_warmth": {"_id": "book_warmth", "title": "The Warmth of Other Suns", "genre": "history"},
    "book_splendid": {"_id": "book_splendid", "title": "The Splendid and the Vile", "genre": "history"},
    "book_dragon_tattoo": {"_id": "book_dragon_tattoo", "title": "The Girl with the Dragon Tattoo", "genre": "thriller"},
    "book_guest_list": {"_id": "book_guest_list", "title": "The Guest List", "genre": "thriller"},
}


def _upsert_catalog(collection, documents: dict[str, dict]) -> None:
    """Set title and genre. Do not delete rows or clear fields already stored."""

    for document_id, document in documents.items():
        result = collection.update_one(
            {"_id": document_id},
            {"$set": {"title": document["title"], "genre": document["genre"]}},
            upsert=True,
        )
        if result.upserted_id is not None:
            print(f"inserted {document_id}")
        elif result.modified_count:
            print(f"updated {document_id}")
        else:
            print(f"already present {document_id}")


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
    print(
        "before "
        f"customers={database.customers.count_documents({})} "
        f"orders={database.orders.count_documents({})} "
        f"returns={database.returns.count_documents({})} "
        f"catalog={database.catalog.count_documents({})}"
    )
    _insert_missing(database.customers, CUSTOMERS)
    _insert_missing(database.paymentMethods, PAYMENTS)
    _insert_missing(database.orders, ORDERS)
    _upsert_catalog(database.catalog, CATALOG)
    completed_returns = database.returns.count_documents({"orderId": "BLY-22018", "status": "completed"})
    print(f"BLY-22018 completed returns: {completed_returns}")
    print(
        "after "
        f"customers={database.customers.count_documents({})} "
        f"orders={database.orders.count_documents({})} "
        f"returns={database.returns.count_documents({})} "
        f"catalog={database.catalog.count_documents({})}"
    )
    client.close()


if __name__ == "__main__":
    main()
