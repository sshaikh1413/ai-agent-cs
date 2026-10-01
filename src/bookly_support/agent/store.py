"""Mongo tools for one signed-in customer. There is no generic query tool."""

from __future__ import annotations

import secrets
from datetime import date, datetime, timezone

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from bookly_support.agent.eligibility import is_eligible
from bookly_support.agent.queries import (
    completed_return,
    get_customer,
    get_order,
    get_payment_method,
    get_policy,
    get_receipt,
    get_session,
    list_recent_orders,
)
from bookly_support.agent.returns import DuplicateReturn, commit_return

RECENT_LIMIT = 10


def _title(document: dict) -> str:
    titles = [
        str(line.get("title"))
        for line in document.get("lines") or []
        if line.get("title")
    ]
    if not titles:
        return "this book"
    if len(titles) == 1:
        return titles[0]
    return ", ".join(titles[:-1]) + " and " + titles[-1]


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class MongoStore:
    def __init__(self, uri: str) -> None:
        self._client = MongoClient(
            uri,
            tz_aware=True,
            serverSelectionTimeoutMS=8000,
            appname="bookly-return-agent",
        )
        self._db = self._client["bookly"]
        self._db.command("ping")
        self._db.returns.create_index(
            [("orderId", 1)],
            unique=True,
            name="uniq_completed_order",
            partialFilterExpression={"status": "completed"},
        )

    def close(self) -> None:
        self._client.close()

    def get_customer(self, customer_id: str) -> dict | None:
        document = self._db.customers.find_one(get_customer(customer_id))
        if document is None:
            return None
        return {
            "id": document["_id"],
            "name": document.get("name") or "",
            "email": document.get("email") or "",
        }

    def list_recent_orders(self, customer_id: str) -> list[dict]:
        cursor = (
            self._db.orders.find(list_recent_orders(customer_id))
            .sort("placedAt", -1)
            .limit(RECENT_LIMIT)
        )
        return [self._order(document) for document in cursor]

    def get_order(self, customer_id: str, order_id: str, today: date) -> dict | None:
        document = self._db.orders.find_one(get_order(customer_id, order_id))
        if document is None:
            return None
        order = self._order(document)
        policy = self._policy()
        order["eligible"] = is_eligible(
            order.get("deliveredAt"),
            today,
            policy["returnWindowDays"],
        )
        order["returnWindowDays"] = policy["returnWindowDays"]
        order["policy"] = policy["body"]
        return order

    def get_refund_options(self, customer_id: str, order_id: str) -> dict | None:
        document = self._db.orders.find_one(get_order(customer_id, order_id))
        if document is None or document.get("refundableCents") is None:
            return None
        payment = None
        payment_id = document.get("paymentMethodId")
        if payment_id:
            payment = self._db.paymentMethods.find_one(
                get_payment_method(customer_id, payment_id)
            )
        last4 = (payment or {}).get("last4")
        brand = (payment or {}).get("brand")
        original: dict = {"available": False}
        if isinstance(last4, str) and last4.strip() and isinstance(brand, str) and brand.strip():
            original = {"available": True, "brand": brand.strip(), "last4": last4.strip()}
        cents = int(document["refundableCents"])
        amount = f"{cents // 100}.{cents % 100:02d}"
        return {
            "orderId": document["_id"],
            "title": _title(document),
            "refundableCents": cents,
            "amount": amount,
            "originalPayment": original,
            "storeCredit": {"available": True, "refundableCents": cents, "amount": amount},
        }

    def start_return(
        self,
        customer_id: str,
        order_id: str,
        destination: str,
        today: date,
        now: datetime,
    ) -> dict:
        existing = self._db.returns.find_one(completed_return(customer_id, order_id))
        if existing is not None:
            return self._replay(customer_id, existing)

        document = self._db.orders.find_one(get_order(customer_id, order_id))
        if document is None:
            return {"status": "not_completed", "reason": "missing_order", "orderId": order_id}
        policy = self._policy()
        delivered = _aware(document.get("deliveredAt"))
        if not is_eligible(delivered, today, policy["returnWindowDays"]):
            return {
                "status": "not_completed",
                "reason": "ineligible",
                "orderId": document["_id"],
                "title": _title(document),
                "returnWindowDays": policy["returnWindowDays"],
                "policy": policy["body"],
            }
        payment = None
        if document.get("paymentMethodId"):
            payment = self._db.paymentMethods.find_one(
                get_payment_method(customer_id, document["paymentMethodId"])
            )
        last4 = (payment or {}).get("last4")
        brand = (payment or {}).get("brand")
        if destination == "original_payment" and not (isinstance(last4, str) and last4.strip()):
            return {
                "status": "not_completed",
                "reason": "card_unavailable",
                "orderId": document["_id"],
                "title": _title(document),
            }
        safe_last4 = last4.strip() if isinstance(last4, str) and last4.strip() else None
        safe_brand = brand.strip() if isinstance(brand, str) and brand.strip() else None
        if destination != "original_payment":
            safe_last4 = None
            safe_brand = None
        return commit_return(
            _MongoReturns(self._db),
            customer_id=customer_id,
            order_id=document["_id"],
            destination=destination,
            title=_title(document),
            amount_cents=int(document["refundableCents"]),
            brand=safe_brand,
            last4=safe_last4,
            now=now,
            new_ids=_new_ids,
        )

    def count_completed_returns(self, customer_id: str, order_id: str) -> int:
        return self._db.returns.count_documents(completed_return(customer_id, order_id))

    def completed_receipt(self, customer_id: str, order_id: str) -> dict | None:
        existing = self._db.returns.find_one(completed_return(customer_id, order_id))
        if existing is None:
            return None
        return self._db.receipts.find_one(get_receipt(customer_id, existing["receiptId"]))

    def create_session(self, customer_id: str) -> dict:
        document = {
            "_id": f"conv_{secrets.token_hex(8)}",
            "customerId": customer_id,
            "phase": "identify_order",
            "orderId": None,
            "destination": None,
            "returnId": None,
            "closedAt": None,
        }
        self._db.sessions.insert_one(document)
        return document

    def load_session(self, customer_id: str, conversation_id: str) -> dict | None:
        return self._db.sessions.find_one(get_session(customer_id, conversation_id))

    def save_session(self, document: dict) -> None:
        self._db.sessions.replace_one(
            get_session(document["customerId"], document["_id"]),
            document,
        )

    def _order(self, document: dict) -> dict:
        return {
            "orderId": document["_id"],
            "title": _title(document),
            "placedAt": _aware(document.get("placedAt")),
            "deliveredAt": _aware(document.get("deliveredAt")),
            "status": document.get("status"),
            "refundableCents": document.get("refundableCents"),
            "paymentMethodId": document.get("paymentMethodId"),
        }

    def _policy(self) -> dict:
        document = self._db.policies.find_one(get_policy())
        if document is None or document.get("returnWindowDays") is None:
            return {
                "returnWindowDays": -1,
                "body": "The return window is not on file, so I can't offer a refund.",
            }
        return {
            "returnWindowDays": int(document["returnWindowDays"]),
            "body": str(document.get("body") or ""),
        }

    def _replay(self, customer_id: str, existing: dict) -> dict:
        receipt = self._db.receipts.find_one(get_receipt(customer_id, existing["receiptId"]))
        if receipt is None:
            return {
                "status": "not_completed",
                "reason": "missing_receipt",
                "orderId": existing.get("orderId"),
            }
        cents = int(receipt["amountCents"])
        return {
            "status": "completed",
            "returnId": existing["_id"],
            "receiptId": receipt["_id"],
            "orderId": receipt["orderId"],
            "customerId": receipt["customerId"],
            "title": receipt["title"],
            "amountCents": cents,
            "amount": f"{cents // 100}.{cents % 100:02d}",
            "destination": receipt["destination"],
            "brand": receipt.get("brand"),
            "last4": receipt.get("last4"),
        }


class _MongoReturns:
    def __init__(self, database) -> None:
        self._db = database

    def find_completed_return(self, customer_id: str, order_id: str) -> dict | None:
        return self._db.returns.find_one(completed_return(customer_id, order_id))

    def find_receipt(self, customer_id: str, receipt_id: str) -> dict | None:
        return self._db.receipts.find_one(get_receipt(customer_id, receipt_id))

    def insert_return_and_receipt(self, return_doc: dict, receipt_doc: dict) -> None:
        try:
            with self._db.client.start_session() as session:
                with session.start_transaction():
                    self._db.returns.insert_one(return_doc, session=session)
                    self._db.receipts.insert_one(receipt_doc, session=session)
        except DuplicateKeyError:
            raise DuplicateReturn from None


def _new_ids() -> tuple[str, str]:
    return f"ret_{secrets.token_hex(6)}", f"rcpt_{secrets.token_hex(6)}"
