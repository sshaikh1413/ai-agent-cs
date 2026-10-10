"""Idempotent return write. A second call returns the receipt already stored."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol


class DuplicateReturn(Exception):
    """A completed return for this order already exists."""


class ReturnRepository(Protocol):
    def find_completed_return(self, customer_id: str, order_id: str) -> dict | None:
        """The completed return for this customer and order, if one exists."""

    def find_receipt(self, customer_id: str, receipt_id: str) -> dict | None:
        """The receipt for this customer, if it exists."""

    def insert_return_and_receipt(self, return_doc: dict, receipt_doc: dict) -> None:
        """Insert both documents, or raise DuplicateReturn."""


def return_permitted(*, eligible: bool, destination: str, exception: bool) -> bool:
    """An order outside the window can be written only as store credit.

    The exception flag does not open a card refund. An eligible order is
    unchanged: Visa or store credit, with no exception required.
    """

    if eligible:
        return True
    return bool(exception) and destination == "store_credit"


def format_amount(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    amount = abs(cents)
    return f"{sign}{amount // 100}.{amount % 100:02d}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _completed(return_doc: dict, receipt_doc: dict) -> dict:
    result = {
        "status": "completed",
        "returnId": return_doc["_id"],
        "receiptId": receipt_doc["_id"],
        "orderId": receipt_doc["orderId"],
        "customerId": receipt_doc["customerId"],
        "title": receipt_doc["title"],
        "amountCents": receipt_doc["amountCents"],
        "amount": format_amount(int(receipt_doc["amountCents"])),
        "destination": receipt_doc["destination"],
        "brand": receipt_doc.get("brand"),
        "last4": receipt_doc.get("last4"),
    }
    if return_doc.get("exception"):
        result["exception"] = True
        result["storeCreditOnly"] = True
        result["refund"] = "store credit"
        tracking = return_doc.get("trackingNumber")
        carrier = return_doc.get("carrier")
        label_id = return_doc.get("labelId")
        if isinstance(tracking, str) and tracking.strip():
            result["trackingNumber"] = tracking.strip()
        if isinstance(carrier, str) and carrier.strip():
            result["carrier"] = carrier.strip()
        if isinstance(label_id, str) and label_id.strip():
            result["labelId"] = label_id.strip()
    return result


def commit_return(
    repo: ReturnRepository,
    *,
    customer_id: str,
    order_id: str,
    destination: str,
    title: str,
    amount_cents: int,
    brand: str | None,
    last4: str | None,
    now: datetime,
    new_ids: Callable[[], tuple[str, str]],
    reason: str | None = None,
    reason_kind: str | None = None,
    sentiment: str | None = None,
    exception: bool = False,
    tracking_number: str | None = None,
    carrier: str | None = None,
    label_id: str | None = None,
) -> dict:
    """Insert a return and its receipt, or return the ones already stored."""

    existing = repo.find_completed_return(customer_id, order_id)
    if existing is not None:
        receipt = repo.find_receipt(customer_id, existing["receiptId"])
        if receipt is None:
            return {"status": "not_completed", "reason": "missing_receipt", "orderId": order_id}
        return _completed(existing, receipt)

    return_id, receipt_id = new_ids()
    return_doc = {
        "_id": return_id,
        "customerId": customer_id,
        "orderId": order_id,
        "destination": destination,
        "amountCents": amount_cents,
        "status": "completed",
        "createdAt": now,
        "receiptId": receipt_id,
        "reason": reason,
        "reasonKind": reason_kind,
        "sentiment": sentiment,
    }
    if exception:
        return_doc["exception"] = True
        if isinstance(tracking_number, str) and tracking_number.strip():
            return_doc["trackingNumber"] = tracking_number.strip()
        if isinstance(carrier, str) and carrier.strip():
            return_doc["carrier"] = carrier.strip()
        if isinstance(label_id, str) and label_id.strip():
            return_doc["labelId"] = label_id.strip()
    receipt_doc = {
        "_id": receipt_id,
        "returnId": return_id,
        "orderId": order_id,
        "customerId": customer_id,
        "title": title,
        "amountCents": amount_cents,
        "destination": destination,
        "brand": brand,
        "last4": last4,
        "issuedAt": now,
    }
    try:
        repo.insert_return_and_receipt(return_doc, receipt_doc)
    except DuplicateReturn:
        existing = repo.find_completed_return(customer_id, order_id)
        if existing is None:
            return {"status": "not_completed", "reason": "write_failed", "orderId": order_id}
        receipt = repo.find_receipt(customer_id, existing["receiptId"])
        if receipt is None:
            return {"status": "not_completed", "reason": "missing_receipt", "orderId": order_id}
        return _completed(existing, receipt)
    return _completed(return_doc, receipt_doc)
