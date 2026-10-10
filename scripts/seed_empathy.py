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

# Title, genre, author, and a one-sentence summary written for this desk.
# Summaries are not publisher blurbs. Upsert fills a missing author and sets
# the summary. An author already stored is left alone. Genre on an existing
# row is left alone, so a horror row stays horror.
CATALOG = {
    "book_piranesi": {"_id": "book_piranesi", "title": "Piranesi", "genre": "fantasy", "author": "Susanna Clarke", "summary": "A man records the tides in a house of statues."},
    "book_hail_mary": {"_id": "book_hail_mary", "title": "Project Hail Mary", "genre": "science fiction", "author": "Andy Weir", "summary": "A teacher wakes alone on a ship and has to learn why the sun is dimming."},
    "book_cerulean": {"_id": "book_cerulean", "title": "The House in the Cerulean Sea", "genre": "fantasy", "author": "TJ Klune", "summary": "A caseworker sent to inspect an orphanage of unusual children finds a home he does not want to close."},
    "book_hill_house": {"_id": "book_hill_house", "title": "The Haunting of Hill House", "genre": "horror", "author": "Shirley Jackson", "summary": "Four guests stay in a house that keeps the one who most wants to belong."},
    "book_dracula": {"_id": "book_dracula", "title": "Dracula", "genre": "horror", "author": "Bram Stoker", "summary": "A lawyer's visit to a Transylvanian count becomes a chase that follows the count to England."},
    "book_frankenstein": {"_id": "book_frankenstein", "title": "Frankenstein", "genre": "horror", "author": "Mary Shelley", "summary": "A student builds a living being, refuses him, and is followed for that refusal."},
    "book_the_shining": {"_id": "book_the_shining", "title": "The Shining", "genre": "horror", "author": "Stephen King", "summary": "A winter caretaker and his family are snowed in at a hotel that wants his temper."},
    "book_carrie": {"_id": "book_carrie", "title": "Carrie", "genre": "horror", "author": "Stephen King", "summary": "A sheltered teenager's humiliation at a school dance ends in a power she can no longer hold."},
    "book_pet_sematary": {"_id": "book_pet_sematary", "title": "Pet Sematary", "genre": "horror", "author": "Stephen King", "summary": "A father finds a burial ground that sends the dead back and uses it when grief will not wait."},
    "book_mexican_gothic": {"_id": "book_mexican_gothic", "title": "Mexican Gothic", "genre": "horror", "author": "Silvia Moreno-Garcia", "summary": "A woman travels to a remote Mexican house and finds the family bound to the walls."},
    "book_midnight_library": {"_id": "book_midnight_library", "title": "The Midnight Library", "genre": "fiction", "author": "Matt Haig", "summary": "A woman who regrets her life steps into a library of other lives she might have lived."},
    "book_circe": {"_id": "book_circe", "title": "Circe", "genre": "fiction", "author": "Madeline Miller", "summary": "A nymph exiled to an island learns witchcraft and outlasts the gods who land there."},
    "book_gentleman": {"_id": "book_gentleman", "title": "A Gentleman in Moscow", "genre": "fiction", "author": "Amor Towles", "summary": "A count under house arrest in a grand hotel builds a whole life inside its rooms."},
    "book_klara": {"_id": "book_klara", "title": "Klara and the Sun", "genre": "fiction", "author": "Kazuo Ishiguro", "summary": "An artificial friend watches the child she was bought for and tries to understand love as sunlight."},
    "book_remains": {"_id": "book_remains", "title": "The Remains of the Day", "genre": "fiction", "author": "Kazuo Ishiguro", "summary": "An English butler looks back on a life of perfect service and the feeling he kept refusing."},
    "book_beloved": {"_id": "book_beloved", "title": "Beloved", "genre": "fiction", "author": "Toni Morrison", "summary": "A formerly enslaved woman in Ohio is visited by the daughter she lost."},
    "book_normal_people": {"_id": "book_normal_people", "title": "Normal People", "genre": "fiction", "author": "Sally Rooney", "summary": "Two classmates in Ireland keep finding and losing each other from school into their twenties."},
    "book_night_circus": {"_id": "book_night_circus", "title": "The Night Circus", "genre": "fantasy", "author": "Erin Morgenstern", "summary": "Two young magicians are bound into a contest that neither was told how to finish."},
    "book_addie": {"_id": "book_addie", "title": "The Invisible Life of Addie LaRue", "genre": "fantasy", "author": "V.E. Schwab", "summary": "A woman cursed to be forgotten spends centuries trying to leave a mark someone will keep."},
    "book_name_of_the_wind": {"_id": "book_name_of_the_wind", "title": "The Name of the Wind", "genre": "fantasy", "author": "Patrick Rothfuss", "summary": "A gifted young man tells how he went from a traveling troupe to a university of magic."},
    "book_dune": {"_id": "book_dune", "title": "Dune", "genre": "science fiction", "author": "Frank Herbert", "summary": "An heir dropped onto a desert planet finds that its spice and its people decide an empire."},
    "book_left_hand": {"_id": "book_left_hand", "title": "The Left Hand of Darkness", "genre": "science fiction", "author": "Ursula K. Le Guin", "summary": "An envoy on a winter planet has to trust someone whose society does not sort people as his does."},
    "book_station_eleven": {"_id": "book_station_eleven", "title": "Station Eleven", "genre": "science fiction", "author": "Emily St. John Mandel", "summary": "After a flu collapses the world, a traveling theater company carries a story between the settlements that remain."},
    "book_the_martian": {"_id": "book_the_martian", "title": "The Martian", "genre": "science fiction", "author": "Andy Weir", "summary": "An astronaut left for dead on Mars has to farm, repair, and signal if he wants a ride home."},
    "book_thursday": {"_id": "book_thursday", "title": "The Thursday Murder Club", "genre": "mystery", "author": "Richard Osman", "summary": "Four friends in a retirement community take on a local killing the police have not solved."},
    "book_gone_girl": {"_id": "book_gone_girl", "title": "Gone Girl", "genre": "mystery", "author": "Gillian Flynn", "summary": "A husband's missing wife becomes a public story, and the marriage behind it was already a contest."},
    "book_silent_patient": {"_id": "book_silent_patient", "title": "The Silent Patient", "genre": "mystery", "author": "Alex Michaelides", "summary": "A therapist tries to learn why a painter stopped speaking after she shot her husband."},
    "book_and_then": {"_id": "book_and_then", "title": "And Then There Were None", "genre": "mystery", "author": "Agatha Christie", "summary": "Ten strangers invited to an island are killed one by one for crimes they thought were buried."},
    "book_pride": {"_id": "book_pride", "title": "Pride and Prejudice", "genre": "romance", "author": "Jane Austen", "summary": "A sharp-tongued woman and a proud man keep misreading each other until both families force a second look."},
    "book_evelyn": {"_id": "book_evelyn", "title": "The Seven Husbands of Evelyn Hugo", "genre": "romance", "author": "Taylor Jenkins Reid", "summary": "An aging film star tells a reporter the real story of her marriages and the love she hid."},
    "book_beach_read": {"_id": "book_beach_read", "title": "Beach Read", "genre": "romance", "author": "Emily Henry", "summary": "Two writers sharing a summer house bet that each can finish the other's kind of book."},
    "book_red_white": {"_id": "book_red_white", "title": "Red, White & Royal Blue", "genre": "romance", "author": "Casey McQuiston", "summary": "The American president's son and a British prince turn a public rivalry into a romance they have to hide."},
    "book_educated": {"_id": "book_educated", "title": "Educated", "genre": "memoir", "author": "Tara Westover", "summary": "A woman raised without school in a survivalist family fights her way to a university and a life of her own."},
    "book_becoming": {"_id": "book_becoming", "title": "Becoming", "genre": "memoir", "author": "Michelle Obama", "summary": "Michelle Obama recounts Chicago, her law career, and the years her family lived in the White House."},
    "book_born_a_crime": {"_id": "book_born_a_crime", "title": "Born a Crime", "genre": "memoir", "author": "Trevor Noah", "summary": "Trevor Noah tells how growing up mixed-race under apartheid shaped the family stories he still tells."},
    "book_sapiens": {"_id": "book_sapiens", "title": "Sapiens", "genre": "history", "author": "Yuval Noah Harari", "summary": "A short history of how humans went from foraging bands to empires, money, and shared stories."},
    "book_warmth": {"_id": "book_warmth", "title": "The Warmth of Other Suns", "genre": "history", "author": "Isabel Wilkerson", "summary": "Three families leave the Jim Crow South and remake their lives in northern and western cities."},
    "book_splendid": {"_id": "book_splendid", "title": "The Splendid and the Vile", "genre": "history", "author": "Erik Larson", "summary": "London's first year with Churchill is told through the Blitz and the people who stayed through it."},
    "book_dragon_tattoo": {"_id": "book_dragon_tattoo", "title": "The Girl with the Dragon Tattoo", "genre": "thriller", "author": "Stieg Larsson", "summary": "A disgraced journalist and a hacker investigate an old disappearance inside a powerful family."},
    "book_guest_list": {"_id": "book_guest_list", "title": "The Guest List", "genre": "thriller", "author": "Lucy Foley", "summary": "A wedding on a remote island becomes a murder, and several guests arrived already carrying a reason."},
}


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _upsert_catalog(collection, documents: dict[str, dict]) -> None:
    """Fill author and summary. Keep an author already stored. Do not change genre."""

    for document_id, document in documents.items():
        existing = collection.find_one({"_id": document_id}, {"author": 1})
        updates = {"title": document["title"], "summary": document["summary"]}
        if existing is None or not _has_text(existing.get("author")):
            updates["author"] = document["author"]
        if existing is None:
            updates["genre"] = document["genre"]
        result = collection.update_one({"_id": document_id}, {"$set": updates}, upsert=True)
        if result.upserted_id is not None:
            print(f"inserted {document_id}")
        elif result.modified_count:
            print(f"updated {document_id}")
        else:
            print(f"already present {document_id}")


def _ensure_order_titles(database, documents: dict[str, dict]) -> None:
    """Add a catalog row when an order title is missing, including author and summary."""

    by_title = {document["title"].casefold(): document for document in documents.values()}
    stocked = {
        str(document.get("title")).strip().casefold()
        for document in database.catalog.find({}, {"title": 1})
        if isinstance(document.get("title"), str) and document["title"].strip()
    }
    for order in database.orders.find({}, {"lines.title": 1}):
        for line in order.get("lines") or []:
            title = line.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            if title.strip().casefold() in stocked:
                continue
            meta = by_title.get(title.strip().casefold())
            if meta is None:
                print(f"order title has no catalog metadata: {title.strip()}")
                continue
            database.catalog.update_one(
                {"_id": meta["_id"]},
                {
                    "$set": {
                        "title": meta["title"],
                        "author": meta["author"],
                        "summary": meta["summary"],
                        "genre": meta["genre"],
                    }
                },
                upsert=True,
            )
            stocked.add(meta["title"].casefold())
            print(f"added order title {meta['_id']}")


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
    _ensure_order_titles(database, CATALOG)
    ready = 0
    horror = 0
    for document in database.catalog.find({}, {"title": 1, "genre": 1, "author": 1, "summary": 1}):
        if str(document.get("genre") or "").strip().casefold() == "horror":
            horror += 1
        if _has_text(document.get("author")) and _has_text(document.get("summary")):
            ready += 1
    print(f"catalog rows with author and summary: {ready}")
    print(f"horror rows: {horror}")
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
