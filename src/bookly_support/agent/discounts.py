"""One goodwill code per customer and order. A second call returns the same code."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

GOODWILL_PERCENT = 20


class DuplicateDiscount(Exception):
    """A goodwill code for this customer and order already exists."""


class DiscountRepository(Protocol):
    def find_discount(self, customer_id: str, order_id: str) -> dict | None:
        """The goodwill discount for this customer and order, if one exists."""

    def insert_discount(self, document: dict) -> None:
        """Insert the discount, or raise DuplicateDiscount."""


def _public(document: dict) -> dict:
    percent = int(document["percent"])
    return {
        "customerId": document["customerId"],
        "orderId": document["orderId"],
        "code": document["code"],
        "percent": percent,
        "percentLabel": f"{percent}%",
        "kind": document.get("kind") or "goodwill",
    }


def issue_goodwill_discount(
    repo: DiscountRepository,
    *,
    customer_id: str,
    order_id: str,
    now: datetime,
    new_code: Callable[[], str],
    new_id: Callable[[], str] | None = None,
) -> dict:
    """Create one 20% code, or return the code already stored for this order."""

    existing = repo.find_discount(customer_id, order_id)
    if existing is not None:
        return _public(existing)

    code = new_code()
    document = {
        "_id": new_id() if new_id is not None else f"disc_{code}",
        "customerId": customer_id,
        "orderId": order_id,
        "code": code,
        "percent": GOODWILL_PERCENT,
        "kind": "goodwill",
        "createdAt": now,
    }
    try:
        repo.insert_discount(document)
    except DuplicateDiscount:
        existing = repo.find_discount(customer_id, order_id)
        if existing is None:
            raise
        return _public(existing)
    return _public(document)
