"""Mongo tools for one signed-in customer. There is no generic query tool."""

from __future__ import annotations

import secrets
from datetime import date, datetime, timezone

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from bookly_support.agent.discounts import DuplicateDiscount
from bookly_support.agent.discounts import issue_goodwill_discount as commit_discount
from bookly_support.agent.eligibility import is_eligible
from bookly_support.agent.label_pdf import (
    CARRIER_NAME,
    LabelFactsError,
    customer_address_lines,
    customer_address_text,
    render_parcel_label,
)
from bookly_support.agent.queries import (
    completed_return,
    completed_return_by_id,
    customer_memory as memory_for_customer,
    get_customer,
    get_label,
    get_order,
    get_payment_method,
    get_policy,
    get_receipt,
    get_session,
    goodwill_discount,
    latest_completed_return,
    list_recent_orders,
)
from bookly_support.agent.receipt_pdf import ReceiptFactsError, render_return_receipt
from bookly_support.agent.recommendations import choose_recommendation
from bookly_support.agent.resolve import longest_catalog_title
from bookly_support.agent.returns import DuplicateReturn, commit_return, return_permitted

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
        self._db.discounts.create_index(
            [("customerId", 1), ("orderId", 1)],
            unique=True,
            name="uniq_customer_order_discount",
        )
        self._db.memory.create_index(
            [("customerId", 1)],
            unique=True,
            name="uniq_customer_memory",
        )
        self._db.labels.create_index(
            [("returnId", 1)],
            unique=True,
            name="uniq_label_return",
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

    def return_window_days(self) -> int:
        """Policy length used to mark a delivered book inside or past the window."""

        return self._policy()["returnWindowDays"]

    def list_recent_orders(self, customer_id: str) -> list[dict]:
        completed = self._completed_order_ids(customer_id)
        cursor = (
            self._db.orders.find(list_recent_orders(customer_id))
            .sort("placedAt", -1)
            .limit(RECENT_LIMIT)
        )
        orders: list[dict] = []
        for document in cursor:
            order = self._order(document)
            if order["orderId"] in completed:
                order["completedReturn"] = True
            orders.append(order)
        return orders

    def _completed_order_ids(self, customer_id: str) -> set[str]:
        """Order ids whose return is already stored with status completed."""

        found: set[str] = set()
        for document in self._db.returns.find(latest_completed_return(customer_id), {"orderId": 1}):
            order_id = document.get("orderId")
            if isinstance(order_id, str) and order_id.strip():
                found.add(order_id)
        return found

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

    def recommend_book(self, customer_id: str, seed: str) -> dict:
        owned: list[str] = []
        for document in self._db.orders.find(list_recent_orders(customer_id)):
            owned.extend(_line_titles(document))
        catalog = list(self._db.catalog.find({}, {"title": 1, "genre": 1, "author": 1}))
        chosen = choose_recommendation(owned, catalog, seed)
        if chosen is None:
            return {"title": None, "genre": None, "author": None}
        return chosen

    def lookup_catalog(self, title: str) -> dict:
        """Author and one-sentence summary for this title, or nulls if it is not stocked."""

        wanted = title.strip().casefold()
        found: dict | None = None
        if wanted:
            for document in self._db.catalog.find({}, {"title": 1, "author": 1, "summary": 1}):
                name = document.get("title")
                if isinstance(name, str) and name.strip().casefold() == wanted:
                    found = document
                    break
        if found is None:
            return {"title": title.strip(), "author": None, "summary": None}
        stored_title = found.get("title")
        return {
            "title": stored_title.strip() if isinstance(stored_title, str) and stored_title.strip() else title.strip(),
            "author": _optional_text(found.get("author")),
            "summary": _optional_text(found.get("summary")),
        }

    def match_catalog_title(self, text: str) -> str | None:
        titles: list[str] = []
        for document in self._db.catalog.find({}, {"title": 1}):
            name = document.get("title")
            if isinstance(name, str) and name.strip():
                titles.append(name.strip())
        return longest_catalog_title(text, titles)

    def issue_goodwill_discount(self, customer_id: str, order_id: str, now: datetime) -> dict:
        document = self._db.orders.find_one(get_order(customer_id, order_id))
        if document is None:
            return {"status": "not_issued", "reason": "missing_order", "orderId": order_id}
        return commit_discount(
            _MongoDiscounts(self._db),
            customer_id=customer_id,
            order_id=document["_id"],
            now=now,
            new_code=_new_discount_code,
            new_id=_new_discount_id,
        )

    def start_return(
        self,
        customer_id: str,
        order_id: str,
        destination: str,
        today: date,
        now: datetime,
        reason: str | None = None,
        reason_kind: str | None = None,
        sentiment: str | None = None,
        exception: bool = False,
    ) -> dict:
        existing = self._db.returns.find_one(completed_return(customer_id, order_id))
        if existing is not None:
            return self._replay(customer_id, existing)

        document = self._db.orders.find_one(get_order(customer_id, order_id))
        if document is None:
            return {"status": "not_completed", "reason": "missing_order", "orderId": order_id}
        policy = self._policy()
        delivered = _aware(document.get("deliveredAt"))
        eligible = is_eligible(delivered, today, policy["returnWindowDays"])
        if not return_permitted(eligible=eligible, destination=destination, exception=exception):
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
        tracking = None
        carrier = None
        label_id = None
        if exception and destination == "store_credit":
            tracking = _new_tracking()
            carrier = CARRIER_NAME
            label_id = _new_label_id()
        result = commit_return(
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
            reason=reason,
            reason_kind=reason_kind,
            sentiment=sentiment,
            exception=exception and destination == "store_credit",
            tracking_number=tracking,
            carrier=carrier,
            label_id=label_id,
        )
        if result.get("status") == "completed" and result.get("exception"):
            self._ensure_label(customer_id, result)
            address = self._address_text(customer_id)
            if address:
                result["address"] = address
        return result

    def latest_completed_return(self, customer_id: str) -> dict | None:
        """Newest completed return for this customer: stored title, and reason text if any."""

        document = self._db.returns.find_one(
            latest_completed_return(customer_id),
            sort=[("createdAt", -1)],
        )
        if document is None or document.get("status") != "completed":
            return None
        title = self._stored_return_title(customer_id, document)
        if not title:
            return None
        reason = document.get("reason")
        reason_text = reason.strip() if isinstance(reason, str) and reason.strip() else None
        return {
            "orderId": document.get("orderId"),
            "title": title,
            "reason": reason_text,
            "reasonKind": _optional_text(document.get("reasonKind")),
            "sentiment": _optional_text(document.get("sentiment")),
        }

    def customer_memory(self, customer_id: str) -> dict | None:
        """What this customer told the desk last time, kept across a demo reset."""

        document = self._db.memory.find_one(memory_for_customer(customer_id))
        if document is None:
            return None
        reason = _optional_text(document.get("reason"))
        title = _optional_text(document.get("title"))
        if reason is None or title is None:
            return None
        order_id = document.get("orderId")
        return {
            "customerId": customer_id,
            "orderId": order_id if isinstance(order_id, str) and order_id.strip() else None,
            "title": title,
            "reason": reason,
            "reasonKind": _optional_text(document.get("reasonKind")),
            "sentiment": _optional_text(document.get("sentiment")),
        }

    def reset_demo(self) -> dict[str, int | str]:
        """Restore returnable orders and clear chats. Memory rows stay."""

        from bookly_support.agent.reset import reset_bookly_demo

        return reset_bookly_demo(self._db)

    def count_completed_returns(self, customer_id: str, order_id: str) -> int:
        return self._db.returns.count_documents(completed_return(customer_id, order_id))

    def completed_receipt(self, customer_id: str, order_id: str) -> dict | None:
        existing = self._db.returns.find_one(completed_return(customer_id, order_id))
        if existing is None:
            return None
        return self._db.receipts.find_one(get_receipt(customer_id, existing["receiptId"]))

    def return_label_pdf(self, customer_id: str, label_id: str) -> bytes | None:
        """PDF for a parcel label already stored for this customer."""

        label = self._db.labels.find_one(get_label(customer_id, label_id))
        if label is None:
            return None
        return_id = label.get("returnId")
        if not isinstance(return_id, str) or not return_id:
            return None
        return_doc = self._db.returns.find_one(completed_return_by_id(customer_id, return_id))
        customer = self._db.customers.find_one(get_customer(customer_id))
        order_id = label.get("orderId")
        if return_doc is None or customer is None or not isinstance(order_id, str):
            return None
        order = self._db.orders.find_one(get_order(customer_id, order_id))
        if order is None:
            return None
        tracking = return_doc.get("trackingNumber") or label.get("trackingNumber")
        carrier = return_doc.get("carrier") or label.get("carrier")
        name = customer.get("name")
        try:
            lines = customer_address_lines(customer)
            if not isinstance(tracking, str) or not isinstance(carrier, str) or not isinstance(name, str):
                return None
            return render_parcel_label(
                name=name,
                address_lines=lines,
                carrier=carrier,
                tracking_number=tracking,
                order_id=order_id,
                title=_title(order),
            )
        except LabelFactsError:
            return None

    def return_receipt_pdf(self, customer_id: str, receipt_id: str) -> bytes | None:
        """PDF for a completed return already stored for this customer."""

        receipt = self._db.receipts.find_one(get_receipt(customer_id, receipt_id))
        if receipt is None or not receipt.get("returnId"):
            return None
        return_doc = self._db.returns.find_one(
            completed_return_by_id(customer_id, receipt["returnId"])
        )
        order_id = receipt.get("orderId")
        if return_doc is None or not isinstance(order_id, str) or not order_id:
            return None
        order = self._db.orders.find_one(get_order(customer_id, order_id))
        customer = self._db.customers.find_one(get_customer(customer_id))
        if order is None or customer is None:
            return None
        try:
            return render_return_receipt(return_doc, order, customer, receipt)
        except ReceiptFactsError:
            return None

    def create_session(self, customer_id: str) -> dict:
        document = {
            "_id": f"conv_{secrets.token_hex(8)}",
            "customerId": customer_id,
            "phase": "identify_order",
            "orderId": None,
            "destination": None,
            "returnId": None,
            "closedAt": None,
            "reason": None,
            "reasonKind": None,
            "sentiment": None,
            "title": None,
            "genre": None,
            "recommendedTitle": None,
            "exception": False,
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
            "genre": _genre(document),
            "deliveredLate": bool(document.get("deliveredLate")),
        } | _status_detail(document)

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

    def _stored_return_title(self, customer_id: str, document: dict) -> str | None:
        receipt_id = document.get("receiptId")
        if isinstance(receipt_id, str) and receipt_id.strip():
            receipt = self._db.receipts.find_one(get_receipt(customer_id, receipt_id.strip()))
            if receipt is not None:
                title = receipt.get("title")
                if isinstance(title, str) and title.strip():
                    return title.strip()
        order_id = document.get("orderId")
        if isinstance(order_id, str) and order_id.strip():
            order = self._db.orders.find_one(get_order(customer_id, order_id.strip()))
            if order is not None:
                title = _title(order)
                if title and title != "this book":
                    return title
        return None

    def _replay(self, customer_id: str, existing: dict) -> dict:
        receipt = self._db.receipts.find_one(get_receipt(customer_id, existing["receiptId"]))
        if receipt is None:
            return {
                "status": "not_completed",
                "reason": "missing_receipt",
                "orderId": existing.get("orderId"),
            }
        cents = int(receipt["amountCents"])
        result = {
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
        if existing.get("exception"):
            result["exception"] = True
            result["storeCreditOnly"] = True
            result["refund"] = "store credit"
            tracking = existing.get("trackingNumber")
            carrier = existing.get("carrier")
            label_id = existing.get("labelId")
            if isinstance(tracking, str) and tracking.strip():
                result["trackingNumber"] = tracking.strip()
            if isinstance(carrier, str) and carrier.strip():
                result["carrier"] = carrier.strip()
            if isinstance(label_id, str) and label_id.strip():
                result["labelId"] = label_id.strip()
            address = self._address_text(customer_id)
            if address:
                result["address"] = address
            self._ensure_label(customer_id, result)
        return result

    def _ensure_label(self, customer_id: str, result: dict) -> None:
        label_id = result.get("labelId")
        tracking = result.get("trackingNumber")
        carrier = result.get("carrier")
        return_id = result.get("returnId")
        order_id = result.get("orderId")
        if not all(isinstance(value, str) and value for value in (label_id, tracking, carrier, return_id, order_id)):
            return
        self._db.labels.update_one(
            {"customerId": customer_id, "returnId": return_id},
            {
                "$setOnInsert": {
                    "_id": label_id,
                    "customerId": customer_id,
                    "returnId": return_id,
                    "orderId": order_id,
                    "trackingNumber": tracking,
                    "carrier": carrier,
                }
            },
            upsert=True,
        )

    def _address_text(self, customer_id: str) -> str | None:
        customer = self._db.customers.find_one(get_customer(customer_id))
        if customer is None:
            return None
        try:
            return customer_address_text(customer)
        except LabelFactsError:
            return None


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


def _new_label_id() -> str:
    return f"lbl_{secrets.token_hex(6)}"


def _new_tracking() -> str:
    return f"BKLY{secrets.token_hex(5).upper()}"


def _new_discount_code() -> str:
    return f"BLY20-{secrets.token_hex(4).upper()}"


def _new_discount_id() -> str:
    return f"disc_{secrets.token_hex(6)}"


def _status_detail(document: dict) -> dict:
    """The stored trip sentence, when this order has one."""

    detail = _optional_text(document.get("statusDetail"))
    if detail is None:
        return {}
    return {"statusDetail": detail}


def _optional_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _line_titles(document: dict) -> list[str]:
    return [
        str(line.get("title")).strip()
        for line in document.get("lines") or []
        if isinstance(line.get("title"), str) and str(line.get("title")).strip()
    ]


def _genre(document: dict) -> str:
    genre = document.get("genre")
    if isinstance(genre, str) and genre.strip():
        return genre.strip().lower()
    for line in document.get("lines") or []:
        line_genre = line.get("genre")
        if isinstance(line_genre, str) and line_genre.strip():
            return line_genre.strip().lower()
    return ""


class _MongoDiscounts:
    def __init__(self, database) -> None:
        self._db = database

    def find_discount(self, customer_id: str, order_id: str) -> dict | None:
        return self._db.discounts.find_one(goodwill_discount(customer_id, order_id))

    def insert_discount(self, document: dict) -> None:
        try:
            self._db.discounts.insert_one(document)
        except DuplicateKeyError:
            raise DuplicateDiscount from None
