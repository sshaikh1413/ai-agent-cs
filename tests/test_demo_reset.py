"""Demo reset and a spoken welcome. No Claude and no Atlas."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from bookly_support.agent.checker import accept_draft, unsupported_facts
from bookly_support.agent.phrasing import phrasing_document
from bookly_support.agent.provider import ChatRequest
from bookly_support.agent.reset import PROTECTED_ORDER_IDS, reset_bookly_demo
from bookly_support.agent.resolve import destination_choice
from bookly_support.agent.return_agent import ReturnAgent
from bookly_support.agent.templates import empathy_other, late_apology, opening_line
from bookly_support.main import app

from test_allowlist import NOW, TODAY
from test_destination import _ready
from test_order_status import PACKED, _machine, _progress
from test_profile_plan_memory import _DeskStore, _orders

ROOT = Path(__file__).resolve().parents[1]
REASON = "it wasn't scary at all"
KEPT = "came in too late. i was trying to gift it"


class _Collection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self.docs = [dict(doc) for doc in docs or []]

    def find(self, query: dict | None = None) -> list[dict]:
        return [doc for doc in self.docs if _match(doc, query or {})]

    def delete_many(self, query: dict) -> None:
        self.docs = [doc for doc in self.docs if not _match(doc, query or {})]

    def update_one(self, filt: dict, update: dict, upsert: bool = False) -> None:
        saved = dict(update.get("$set", {}))
        for doc in self.docs:
            if _match(doc, filt):
                doc.update(saved)
                return
        if upsert:
            self.docs.append(saved)

    def create_index(self, *args, **kwargs) -> None:
        del args, kwargs


def _match(document: dict, query: dict) -> bool:
    for key, expected in query.items():
        value = document.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if value not in expected["$in"]:
                return False
        elif value != expected:
            return False
    return True


class _Database:
    def __init__(self) -> None:
        when = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
        earlier = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
        later = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
        self.customers = _Collection(
            [
                {"_id": "cust_becky", "name": "Becky Alvarez"},
                {"_id": "cust_bob", "name": "Bob Hale"},
            ]
        )
        self.catalog = _Collection(
            [
                {"_id": "book_mexican_gothic", "title": "Mexican Gothic"},
                {"_id": "book_midnight_library", "title": "The Midnight Library"},
            ]
        )
        self.policies = _Collection(
            [
                {"_id": "return-window", "returnWindowDays": 30, "body": "Delivered books can be returned within 30 days."},
                {
                    "_id": "shipping-speed",
                    "kind": "article",
                    "topic": "Shipping speed and price",
                    "body": "Standard shipping takes 5–7 business days.",
                },
            ]
        )
        self.orders = _Collection(
            [
                {"_id": "BLY-22018", "status": "delivered", "lines": [{"title": "The Midnight Library"}]},
                {"_id": "BLY-22002", "status": "delivered", "lines": [{"title": "Circe"}]},
                {"_id": "BLY-22044", "status": "delivered", "lines": [{"title": "Mexican Gothic"}]},
                {"_id": "BLY-33010", "status": "delivered", "lines": [{"title": "A Gentleman in Moscow"}]},
                {"_id": "BLY-44120", "status": "packing", "lines": [{"title": "Klara and the Sun"}]},
                {"_id": "BLY-44121", "status": "shipped", "lines": [{"title": "The Night Circus"}]},
                {"_id": "BLY-44122", "status": "on the way", "lines": [{"title": "Educated"}]},
                {"_id": "BLY-44123", "status": "out for delivery", "lines": [{"title": "Beach Read"}]},
            ]
        )
        self.sessions = _Collection(
            [{"_id": "conv_demo", "customerId": "cust_becky", "phase": "choose_destination"}]
        )
        self.returns = _Collection(
            [
                {
                    "_id": "ret_old",
                    "customerId": "cust_becky",
                    "orderId": "BLY-22002",
                    "status": "completed",
                    "reason": "changed my mind",
                    "reasonKind": "other",
                    "sentiment": "neutral",
                    "receiptId": "rcpt_old",
                    "createdAt": earlier,
                },
                {
                    "_id": "ret_scary",
                    "customerId": "cust_becky",
                    "orderId": "BLY-22044",
                    "status": "completed",
                    "reason": REASON,
                    "reasonKind": "other",
                    "sentiment": "negative",
                    "receiptId": "rcpt_scary",
                    "createdAt": when,
                },
                {
                    "_id": "ret_midnight",
                    "customerId": "cust_becky",
                    "orderId": "BLY-22018",
                    "status": "completed",
                    "reason": None,
                    "receiptId": "rcpt_midnight",
                    "createdAt": later,
                },
                {
                    "_id": "ret_progress",
                    "customerId": "cust_becky",
                    "orderId": "BLY-44120",
                    "status": "completed",
                    "reason": "leave this return",
                    "receiptId": "rcpt_progress",
                    "createdAt": when,
                },
            ]
        )
        self.receipts = _Collection(
            [
                {"_id": "rcpt_old", "returnId": "ret_old", "orderId": "BLY-22002", "title": "Circe"},
                {"_id": "rcpt_scary", "returnId": "ret_scary", "orderId": "BLY-22044", "title": "Mexican Gothic"},
                {
                    "_id": "rcpt_midnight",
                    "returnId": "ret_midnight",
                    "orderId": "BLY-22018",
                    "title": "The Midnight Library",
                },
                {
                    "_id": "rcpt_progress",
                    "returnId": "ret_progress",
                    "orderId": "BLY-44120",
                    "title": "Klara and the Sun",
                },
            ]
        )
        self.discounts = _Collection(
            [
                {"_id": "disc_late", "customerId": "cust_bob", "orderId": "BLY-33010", "code": "BLY20-KEEP0001"},
                {"_id": "disc_progress", "customerId": "cust_becky", "orderId": "BLY-44121", "code": "BLY20-STAY0001"},
            ]
        )
        self.memory = _Collection(
            [
                {
                    "customerId": "cust_bob",
                    "orderId": "BLY-33010",
                    "title": "A Gentleman in Moscow",
                    "reason": KEPT,
                    "reasonKind": "late_delivery",
                    "sentiment": "negative",
                }
            ]
        )


def _copy(collection: _Collection) -> list[dict]:
    return [dict(doc) for doc in collection.docs]


def test_reset_clears_the_session_and_return_and_keeps_the_reason() -> None:
    database = _Database()
    orders = _copy(database.orders)
    customers = _copy(database.customers)
    catalog = _copy(database.catalog)
    policies = _copy(database.policies)
    result = reset_bookly_demo(database)

    assert result["status"] == "reset"
    assert database.sessions.docs == []
    assert {doc["_id"] for doc in database.returns.docs} == {"ret_progress"}
    assert {doc["_id"] for doc in database.receipts.docs} == {"rcpt_progress"}
    assert {doc["_id"] for doc in database.discounts.docs} == {"disc_progress"}
    assert database.orders.docs == orders
    assert database.customers.docs == customers
    assert database.catalog.docs == catalog
    assert database.policies.docs == policies
    statuses = {doc["_id"]: doc["status"] for doc in database.orders.docs}
    assert statuses["BLY-22018"] == "delivered"
    assert statuses["BLY-22002"] == "delivered"
    assert statuses["BLY-22044"] == "delivered"
    assert statuses["BLY-33010"] == "delivered"
    for order_id in PROTECTED_ORDER_IDS:
        assert statuses[order_id] == orders_status(orders, order_id)

    becky = next(doc for doc in database.memory.docs if doc["customerId"] == "cust_becky")
    assert becky["orderId"] == "BLY-22044"
    assert becky["title"] == "Mexican Gothic"
    assert becky["reason"] == REASON
    assert becky["reasonKind"] == "other"
    assert becky["sentiment"] == "negative"
    assert all(doc.get("orderId") != "BLY-22018" for doc in database.memory.docs)
    assert all(doc.get("reason") != "leave this return" for doc in database.memory.docs)

    bob = next(doc for doc in database.memory.docs if doc["customerId"] == "cust_bob")
    assert bob["reason"] == KEPT
    assert bob["orderId"] == "BLY-33010"
    assert len(database.memory.docs) == 2


def orders_status(orders: list[dict], order_id: str) -> str:
    return next(doc["status"] for doc in orders if doc["_id"] == order_id)


def test_reset_route_is_the_demo_control() -> None:
    class _Store:
        def reset_demo(self) -> dict[str, int | str]:
            return {
                "status": "reset",
                "sessionsCleared": 1,
                "returnsRemoved": 1,
                "discountsRemoved": 1,
                "memoriesKept": 1,
            }

    class _Agent:
        store = _Store()

    app.state.agent = _Agent()
    try:
        with TestClient(app) as client:
            response = client.post("/api/demo/reset")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "reset"
        assert body["sessionsCleared"] == 1
        assert "reason" not in body
    finally:
        if hasattr(app.state, "agent"):
            del app.state.agent


class _Remembering(_DeskStore):
    def customer_memory(self, customer_id: str) -> dict:
        assert customer_id == "cust_becky"
        return {
            "customerId": "cust_becky",
            "orderId": "BLY-22044",
            "title": "Mexican Gothic",
            "reason": REASON,
            "reasonKind": "other",
            "sentiment": "negative",
        }


class _Recording:
    def __init__(self) -> None:
        self.memory = None

    def phrase(self, turn, message: str, customer_name: str | None = None, memory: dict | None = None):
        del turn, message, customer_name
        self.memory = memory
        return f"You said {REASON}."


def test_opening_does_not_contain_the_stored_reason() -> None:
    assert opening_line("Becky Alvarez") == "Becky, it's good to see you again."
    assert REASON not in opening_line("Becky Alvarez")
    assert KEPT not in opening_line("Bob Hale")
    store = _Remembering(_orders(), "cust_becky", "Becky Alvarez", None)
    info = ReturnAgent(store, _Recording()).desk("cust_becky")
    assert info.opening == "Becky, it's good to see you again."
    assert REASON not in (info.opening or "")
    assert "You said" not in (info.opening or "")


def test_reply_template_does_not_paste_you_said() -> None:
    source = (ROOT / "src" / "bookly_support" / "agent" / "templates.py").read_text()
    assert "You said" not in source
    heard = empathy_other("Circe", "changed_mind", "neutral")
    assert "You said" not in heard
    assert "you said" not in heard.lower()
    assert heard == "No problem at all. Plans change."
    assert "I hear you" not in empathy_other("Circe", "not_for_me", "negative")
    assert "You said" not in late_apology("A Gentleman in Moscow", "it arrived late", None)

    phraser = _Recording()
    store = _Remembering(_orders(), "cust_becky", "Becky Alvarez", None)
    reply = ReturnAgent(store, phraser).reply(
        ChatRequest(message="I want to return a product", customer_id="cust_becky")
    )
    assert phraser.memory is not None
    assert phraser.memory["reason"] == REASON
    document = phrasing_document(
        type("Turn", (), {"instruction": "hello", "payload": {"results": []}})(),
        "I want to return a product",
        "Becky Alvarez",
        phraser.memory,
    )
    assert document["memory"]["reason"] == REASON
    assert "do not recite" in document["memory"]["instruction"].lower()
    assert REASON not in reply.reply
    assert "You said" not in reply.reply
    assert reply.step == "Step: which order"


def test_checker_replaces_a_recited_reason_and_a_gift_they_did_not_mention() -> None:
    template = "I can help with a return. Which one do you want to return?"
    recited = f"You said {KEPT}."
    assert accept_draft(recited, template, {"results": []}, [], "where is my order", KEPT) == template
    brought = "It came in too late and you were trying to gift it."
    assert accept_draft(brought, template, {"results": []}, [], KEPT, KEPT) == brought

    payload = {
        "reason": "delivery too late",
        "results": [
            {
                "title": "A Gentleman in Moscow",
                "percent": 20,
                "percentLabel": "20%",
                "code": "BLY20-ABC12345",
            }
        ],
    }
    grounded = "I'm sorry A Gentleman in Moscow arrived late."
    gift = "I'm sorry the gift was missed. Code BLY20-ABC12345 is 20% off."
    assert any("gift" in item.lower() for item in unsupported_facts(gift, payload))
    assert any("BLY-99999" in item for item in unsupported_facts("Order BLY-99999.", payload))
    assert accept_draft(gift, grounded, payload, ["20%", "BLY20-ABC12345"]) == grounded


def test_card_is_fine_still_selects_visa() -> None:
    _store, machine, session = _ready()
    done = machine.step(session, "card is fine", today=TODAY, now=NOW)
    assert done.tools[0].payload["destination"] == "original_payment"
    assert "Visa" in done.template
    assert done.step == "Step: receipt"


def test_status_question_returns_the_stored_status() -> None:
    _store, machine, session = _machine([_progress("BLY-44120", "Klara and the Sun", "packing", PACKED)])
    turn = machine.step(session, "what's the status of BLY-44120", today=TODAY, now=NOW)
    assert turn.step == "Step: order status"
    assert turn.tools[0].payload["status"] == "packing"
    assert turn.tools[0].payload["statusDetail"] == PACKED
    assert "packing" in turn.template
    assert PACKED in turn.template
    assert session.phase == "identify_order"
