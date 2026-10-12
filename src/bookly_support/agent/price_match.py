"""Price match: keep the book and get the difference back when it is cheaper elsewhere.

There is no connection to another store. ``competitor_price`` is a stand-in for a
price lookup and reports the price the reader gave as found. The match itself is
real: one record per order, and the difference goes to the card on file (or store
credit when there is no card).
"""

from __future__ import annotations

import secrets
from datetime import datetime

from bookly_support.agent.returns import format_amount


def competitor_price(title: str, store: str, price_cents: int) -> dict:
    """Simulated lookup at another store. Nothing external is called."""

    return {
        "found": True,
        "simulated": True,
        "store": store,
        "title": title,
        "priceCents": int(price_cents),
        "price": format_amount(int(price_cents)),
    }


def price_match_record(
    *,
    customer_id: str,
    order_id: str,
    title: str,
    paid_cents: int,
    store: str,
    price_cents: int,
    payment: dict | None,
    now: datetime,
) -> dict:
    """The record to store, or a not_lower result when the price is not below what they paid."""

    base = {
        "customerId": customer_id,
        "orderId": order_id,
        "title": title,
        "store": store,
        "priceCents": int(price_cents),
        "paidCents": int(paid_cents),
    }
    if price_cents <= 0 or price_cents >= paid_cents:
        return {**base, "status": "not_lower"}
    brand = (payment or {}).get("brand")
    last4 = (payment or {}).get("last4")
    card = isinstance(brand, str) and brand.strip() and isinstance(last4, str) and last4.strip()
    return {
        **base,
        "_id": "match_" + secrets.token_hex(6),
        "status": "matched",
        "differenceCents": int(paid_cents) - int(price_cents),
        "destination": "original_payment" if card else "store_credit",
        "brand": brand.strip() if card else None,
        "last4": last4.strip() if card else None,
        "createdAt": now,
    }


def price_match_result(record: dict) -> dict:
    """The tool payload: amounts as cents and as "12.99" strings, for the reply and the checker."""

    result = {
        "status": record["status"],
        "orderId": record["orderId"],
        "title": record["title"],
        "store": record["store"],
        "priceCents": record["priceCents"],
        "price": format_amount(record["priceCents"]),
        "paidCents": record["paidCents"],
        "paid": format_amount(record["paidCents"]),
    }
    if record["status"] == "matched":
        result.update(
            {
                "differenceCents": record["differenceCents"],
                "difference": format_amount(record["differenceCents"]),
                "destination": record["destination"],
                "brand": record.get("brand"),
                "last4": record.get("last4"),
            }
        )
    return result
