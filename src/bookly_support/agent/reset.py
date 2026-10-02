"""Put the demo back at its starting orders without erasing what a reader said.

Customers, catalog rows, and in-progress orders stay. A completed return's
reason is copied onto a memory row before that return is removed. A return
with no reason does not gain one, and memory rows already stored are left
in place when this run has nothing new to remember.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

RETURNABLE_ORDER_IDS = frozenset(
    {"BLY-22018", "BLY-22002", "BLY-22044", "BLY-33010", "BLY-18440"}
)
PROTECTED_ORDER_IDS = ("BLY-44120", "BLY-44121", "BLY-44122", "BLY-44123")


@dataclass(frozen=True)
class DemoResetPlan:
    """Ids to remove, and memory rows to upsert. Orders are not in here."""

    memory_upserts: tuple[dict, ...]
    return_ids: tuple[str, ...]
    receipt_ids: tuple[str, ...]
    discount_ids: tuple[str, ...]
    label_ids: tuple[str, ...]


def plan_demo_reset(
    *,
    returns: list[dict],
    receipts: list[dict],
    discounts: list[dict],
    orders: list[dict],
    labels: list[dict] | None = None,
) -> DemoResetPlan:
    """Choose what a reset removes. Memory is only the reason they actually stored."""

    chosen: dict[str, tuple[float, dict]] = {}
    return_ids: list[str] = []
    for document in returns:
        order_id = document.get("orderId")
        if order_id not in RETURNABLE_ORDER_IDS:
            continue
        return_id = document.get("_id")
        if isinstance(return_id, str) and return_id:
            return_ids.append(return_id)
        record = memory_from_return(document, _return_title(document, receipts, orders))
        if record is None:
            continue
        stamp = _stamp(document)
        current = chosen.get(record["customerId"])
        if current is None or stamp >= current[0]:
            chosen[record["customerId"]] = (stamp, record)

    removed = set(return_ids)
    receipt_ids = [
        receipt["_id"]
        for receipt in receipts
        if isinstance(receipt.get("_id"), str)
        and (
            receipt.get("orderId") in RETURNABLE_ORDER_IDS
            or receipt.get("returnId") in removed
        )
    ]
    discount_ids = [
        discount["_id"]
        for discount in discounts
        if isinstance(discount.get("_id"), str) and discount.get("orderId") in RETURNABLE_ORDER_IDS
    ]
    label_ids = [
        label["_id"]
        for label in labels or []
        if isinstance(label.get("_id"), str)
        and (
            label.get("returnId") in removed
            or label.get("orderId") in RETURNABLE_ORDER_IDS
        )
    ]
    upserts = tuple(record for _, record in chosen.values())
    return DemoResetPlan(
        memory_upserts=upserts,
        return_ids=tuple(return_ids),
        receipt_ids=tuple(receipt_ids),
        discount_ids=tuple(discount_ids),
        label_ids=tuple(label_ids),
    )


def memory_from_return(document: dict, title: str | None) -> dict | None:
    """One customer's memory, or None when the return has no stored reason."""

    order_id = document.get("orderId")
    if order_id not in RETURNABLE_ORDER_IDS:
        return None
    reason = _text(document.get("reason"))
    customer_id = _text(document.get("customerId"))
    kept_title = _text(title)
    if reason is None or customer_id is None or kept_title is None:
        return None
    return {
        "customerId": customer_id,
        "orderId": order_id,
        "title": kept_title,
        "reason": reason,
        "reasonKind": _text(document.get("reasonKind")),
        "sentiment": _text(document.get("sentiment")),
    }


def reset_bookly_demo(database) -> dict[str, int | str]:
    """Clear demo sessions, returns, and goodwill discounts. Keep memory and orders."""

    index = getattr(database.memory, "create_index", None)
    if index is not None:
        index([("customerId", 1)], unique=True, name="uniq_customer_memory")

    orders_before = _snapshot(database.orders)
    customers_before = _snapshot(database.customers)
    catalog_before = _snapshot(database.catalog)

    sessions = list(database.sessions.find({}))
    returns = list(database.returns.find({}))
    receipts = list(database.receipts.find({}))
    discounts = list(database.discounts.find({}))
    orders = list(database.orders.find({}))
    labels_collection = getattr(database, "labels", None)
    labels = list(labels_collection.find({})) if labels_collection is not None else []
    plan = plan_demo_reset(
        returns=returns,
        receipts=receipts,
        discounts=discounts,
        orders=orders,
        labels=labels,
    )

    for record in plan.memory_upserts:
        database.memory.update_one(
            {"customerId": record["customerId"]},
            {"$set": dict(record)},
            upsert=True,
        )
    database.returns.delete_many({"_id": {"$in": list(plan.return_ids)}})
    database.receipts.delete_many({"_id": {"$in": list(plan.receipt_ids)}})
    database.discounts.delete_many({"_id": {"$in": list(plan.discount_ids)}})
    if labels_collection is not None:
        labels_collection.delete_many({"_id": {"$in": list(plan.label_ids)}})
    database.sessions.delete_many({})

    if _snapshot(database.orders) != orders_before:
        raise RuntimeError("Reset changed an order.")
    if _snapshot(database.customers) != customers_before:
        raise RuntimeError("Reset changed a customer.")
    if _snapshot(database.catalog) != catalog_before:
        raise RuntimeError("Reset changed the catalog.")

    return {
        "status": "reset",
        "sessionsCleared": len(sessions),
        "returnsRemoved": len(plan.return_ids),
        "discountsRemoved": len(plan.discount_ids),
        "memoriesKept": len(list(database.memory.find({}))),
    }


def _return_title(document: dict, receipts: list[dict], orders: list[dict]) -> str | None:
    receipt_id = document.get("receiptId")
    return_id = document.get("_id")
    for receipt in receipts:
        same_receipt = receipt_id is not None and receipt.get("_id") == receipt_id
        same_return = return_id is not None and receipt.get("returnId") == return_id
        if same_receipt or same_return:
            title = _text(receipt.get("title"))
            if title:
                return title
    order_id = document.get("orderId")
    for order in orders:
        if order.get("_id") == order_id or order.get("orderId") == order_id:
            return _order_title(order)
    return None


def _order_title(order: dict) -> str | None:
    titles: list[str] = []
    for line in order.get("lines") or []:
        if not isinstance(line, dict):
            continue
        title = _text(line.get("title"))
        if title:
            titles.append(title)
    if not titles:
        return _text(order.get("title"))
    if len(titles) == 1:
        return titles[0]
    return ", ".join(titles[:-1]) + " and " + titles[-1]


def _stamp(document: dict) -> float:
    value = document.get("createdAt")
    if isinstance(value, datetime):
        return value.timestamp()
    return float("-inf")


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _snapshot(collection) -> tuple[str, ...]:
    rows = [
        json.dumps(document, sort_keys=True, default=str)
        for document in collection.find({})
    ]
    return tuple(sorted(rows))
