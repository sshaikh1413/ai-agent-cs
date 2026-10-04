"""Upsert Bookly policy articles. Does not touch customer records.

Reads MONGODB_URI from the environment. Does not print the URI. Does not delete
customers, orders, returns, discounts, catalog, or sessions. Does not change
the existing return-window day count.
"""

from __future__ import annotations

import os
import sys

from pymongo import MongoClient

from bookly_support.agent.articles import ARTICLES, article_document
from bookly_support.config import POLICY_ID

_KEPT = ("customers", "orders", "returns", "discounts", "catalog", "sessions")


def upsert_policy_articles(database) -> tuple[list[str], int]:
    """Replace each article by id. Leave the return-window document's day count."""

    before = {name: database[name].count_documents({}) for name in _KEPT}
    window = database.policies.find_one({"_id": POLICY_ID}, {"returnWindowDays": 1})
    if window is None or window.get("returnWindowDays") is None:
        raise RuntimeError("The return-window policy is missing.")
    days = int(window["returnWindowDays"])
    if days < 1:
        raise RuntimeError("The return-window policy has no day count.")

    stored: list[str] = []
    for article in ARTICLES:
        document = article_document(article)
        if document.get("usesReturnWindow") and str(days) in document["body"]:
            raise RuntimeError("Refusing to store a second copy of the return window.")
        database.policies.replace_one({"_id": document["_id"]}, document, upsert=True)
        stored.append(document["_id"])

    after = {name: database[name].count_documents({}) for name in _KEPT}
    if after != before:
        raise RuntimeError("Seeding changed a customer collection.")
    kept = database.policies.find_one({"_id": POLICY_ID}, {"returnWindowDays": 1})
    if kept is None or int(kept["returnWindowDays"]) != days:
        raise RuntimeError("Seeding changed the return window.")
    return stored, days


def main() -> None:
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        print("MONGODB_URI is not set.", file=sys.stderr)
        raise SystemExit(1)
    client = MongoClient(uri, serverSelectionTimeoutMS=8000, appname="bookly-policy-seed")
    try:
        database = client["bookly"]
        database.command("ping")
        stored, days = upsert_policy_articles(database)
    except Exception as exc:
        print(f"Policy seed failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        client.close()
    print(f"returnWindowDays {days}")
    print("stored " + ", ".join(stored))


if __name__ == "__main__":
    main()
