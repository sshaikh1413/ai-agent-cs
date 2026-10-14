"""Give every catalog title a price, so Mara can sell a book she recommends.

Titles Becky and Bob already bought keep the price on their orders. Every other
title gets a stable price from a small list. Only titles without a price are
changed. Reads MONGODB_URI from the environment and does not print it.
"""

from __future__ import annotations

import hashlib
import os

from pymongo import MongoClient

KNOWN_CENTS = {
    "A Gentleman in Moscow": 1800,
    "Beach Read": 1600,
    "Circe": 1700,
    "Educated": 1800,
    "Klara and the Sun": 1700,
    "Mexican Gothic": 1699,
    "Piranesi": 1599,
    "The Midnight Library": 1699,
    "The Night Circus": 1699,
}
LIST_CENTS = (1499, 1599, 1699, 1799, 1899)


def price_cents(title: str) -> int:
    if title in KNOWN_CENTS:
        return KNOWN_CENTS[title]
    digest = int(hashlib.sha256(title.encode("utf-8")).hexdigest(), 16)
    return LIST_CENTS[digest % len(LIST_CENTS)]


def main() -> None:
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        raise SystemExit("MONGODB_URI is not set")
    client = MongoClient(uri, serverSelectionTimeoutMS=12000, appname="bookly-seed")
    catalog = client["bookly"].catalog
    priced = 0
    for row in catalog.find({"priceCents": {"$exists": False}}, {"title": 1}):
        title = row.get("title")
        if isinstance(title, str) and title.strip():
            catalog.update_one({"_id": row["_id"]}, {"$set": {"priceCents": price_cents(title.strip())}})
            priced += 1
    print(f"priced {priced} titles; {catalog.count_documents({'priceCents': {'$exists': True}})} of {catalog.count_documents({})} have a price")
    client.close()


if __name__ == "__main__":
    main()
