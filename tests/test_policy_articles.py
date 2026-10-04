"""Shop policy articles. No Claude and no Atlas."""

import re
from datetime import date, datetime, timezone

from bookly_support.agent.articles import ARTICLES, public_article
from bookly_support.agent.checker import accept_draft, facts_allowed, unsupported_facts
from bookly_support.agent.machine import Machine, Session

from test_allowlist import NOW, TODAY, FakeStore, _order

_SENT = re.compile(
    r"\b(?:we|i|we've|i've)\s+(?:just\s+)?(?:emailed|sent)\b"
    r"|\bemailed you\b|\bsent you\b|\bcode was sent\b",
    re.IGNORECASE,
)
_ACCOUNT = re.compile(
    r"\bhas an account\b|\bno account\b|\baccount exists\b|\baccount does not exist\b",
    re.IGNORECASE,
)


def _desk() -> tuple[FakeStore, Machine, Session]:
    store = FakeStore(
        [
            _order("BLY-22018", "The Midnight Library", date(2026, 9, 24), date(2026, 9, 26), 1699),
            {
                "orderId": "BLY-44121",
                "title": "The Night Circus",
                "placedAt": datetime(2026, 10, 1, 16, tzinfo=timezone.utc),
                "deliveredAt": None,
                "status": "shipped",
                "statusDetail": "It left the Bookly warehouse this morning.",
                "refundableCents": 1699,
                "paymentMethodId": "pm_becky_visa",
            },
        ]
    )
    return store, Machine(store), Session(id="conv_policy", customer_id="cust_becky")


def test_the_return_window_number_is_not_stored_twice() -> None:
    raw = next(article for article in ARTICLES if article["id"] == "returns")
    assert "{days}" in raw["body"]
    assert re.search(r"\d", raw["body"]) is None
    rendered = public_article(raw, 30)
    assert rendered["returnWindowDays"] == 30
    assert rendered["body"].count("30") == 1
    assert "30 days of delivery" in rendered["body"]
    other = public_article(raw, 14)
    assert "14 days of delivery" in other["body"]
    assert "30" not in other["body"]


def test_shipping_question_returns_the_stored_window_not_another_number() -> None:
    store, machine, session = _desk()
    turn = machine.step(session, "How long does shipping take?", today=TODAY, now=NOW)
    assert [tool.name for tool in turn.tools] == ["get_policy_article"]
    assert turn.tools[0].payload["id"] == "shipping-speed"
    assert "5\u20137 business days" in turn.template
    assert "$5.99" in turn.template
    assert "$35" in turn.template
    assert "3 business days" not in turn.template
    assert "2-day" not in turn.template
    assert facts_allowed(turn.template, turn.payload)
    assert any("3" in item for item in unsupported_facts("Standard shipping takes 3 business days.", turn.payload))
    assert any("9.99" in item for item in unsupported_facts("Shipping is $9.99.", turn.payload))
    assert session.phase == "identify_order"
    assert "start_return" not in store.calls


def test_password_question_does_not_claim_a_code_was_sent() -> None:
    _store, machine, session = _desk()
    for phrase in ("I forgot my password", "I'm locked out", "reset my password"):
        session = Session(id="conv_policy", customer_id="cust_becky")
        turn = machine.step(session, phrase, today=TODAY, now=NOW)
        assert [tool.name for tool in turn.tools] == ["get_policy_article"], phrase
        assert turn.tools[0].payload["id"] == "sign-in"
        assert turn.intent == "password_reset"
        assert "does not send that code" in turn.template
        assert _SENT.search(turn.template) is None
        assert "@" not in turn.template
        assert _ACCOUNT.search(turn.template) is None
        assert "type a password" in turn.template
        assert facts_allowed(turn.template, turn.payload)
        bad = "We emailed you a code at becky@example.com and that email has an account."
        assert accept_draft(bad, turn.template, turn.payload, turn.required) == turn.template
        assert session.phase == "identify_order"


def test_where_is_my_order_still_uses_the_status_tool() -> None:
    store, machine, session = _desk()
    turn = machine.step(session, "where is my order", today=TODAY, now=NOW)
    assert turn.step == "Step: order status"
    assert turn.tools
    assert all(tool.name != "get_policy_article" for tool in turn.tools)
    assert turn.tools[0].name in {"get_order", "list_recent_orders"}
    named = machine.step(
        Session(id="conv_night", customer_id="cust_becky"),
        "Where is The Night Circus?",
        today=TODAY,
        now=NOW,
    )
    assert named.step == "Step: order status"
    assert [tool.name for tool in named.tools] == ["get_order"]
    assert named.tools[0].payload["orderId"] == "BLY-44121"
    assert "The Night Circus" in named.template
    assert "shipped" in named.template
    assert all(tool.name != "get_policy_article" for tool in named.tools)
    assert "start_return" not in store.calls


def test_a_weak_match_asks_which_topic() -> None:
    store, machine, session = _desk()
    turn = machine.step(session, "shipping and tax", today=TODAY, now=NOW)
    assert turn.step == "Step: which topic"
    assert "which topic" in turn.template.lower()
    assert turn.tools == []
    assert {choice.order_id for choice in turn.choices} >= {"shipping-speed", "sign-in", "returns"}
    assert all(choice.mark == "Policy" for choice in turn.choices)
    clicked = machine.step(session, turn.choices[0].order_id, today=TODAY, now=NOW)
    assert [tool.name for tool in clicked.tools] == ["get_policy_article"]
    assert clicked.tools[0].payload["id"] == turn.choices[0].order_id
    assert clicked.template == clicked.tools[0].payload["body"]
    assert facts_allowed(clicked.template, clicked.payload)
    assert "start_return" not in store.calls


def test_my_discount_code_comes_from_the_customer_row() -> None:
    store, machine, session = _desk()
    empty = machine.step(session, "what's my discount code?", today=TODAY, now=NOW)
    assert [tool.name for tool in empty.tools] == ["list_customer_discounts"]
    assert empty.tools[0].payload == {"discounts": []}
    assert empty.template == "I don't see a discount code on this account."
    assert "BLY" not in empty.template
    assert facts_allowed(empty.template, empty.payload)

    store.discounts.docs["disc_one"] = {
        "_id": "disc_one",
        "customerId": "cust_becky",
        "orderId": "BLY-22018",
        "code": "BLY20-ABC12345",
        "percent": 20,
    }
    found = machine.step(
        Session(id="conv_code", customer_id="cust_becky"),
        "what's my discount code",
        today=TODAY,
        now=NOW,
    )
    assert found.tools[0].name == "list_customer_discounts"
    assert "BLY20-ABC12345" in found.template
    assert "20%" in found.template
    assert facts_allowed(found.template, found.payload)
    invented = found.template.replace("BLY20-ABC12345", "BLY20-NOPE9999")
    assert accept_draft(invented, found.template, found.payload, found.required) == found.template

    how = machine.step(
        Session(id="conv_how", customer_id="cust_becky"),
        "How do I enter a discount code?",
        today=TODAY,
        now=NOW,
    )
    assert how.tools[0].name == "get_policy_article"
    assert how.tools[0].payload["id"] == "discount-code"
    assert "BLY20" not in how.template
    assert "discount box" in how.template


def test_cancel_and_address_articles_do_not_write() -> None:
    store, machine, session = _desk()
    cancel = machine.step(session, "Can I cancel my order?", today=TODAY, now=NOW)
    assert cancel.tools[0].payload["id"] == "cancel"
    assert "only while its status is packing" in cancel.template
    assert "does not cancel" in cancel.template
    assert "start_return" not in store.calls
    assert session.order_id is None
    assert session.phase == "identify_order"

    address = machine.step(
        Session(id="conv_address", customer_id="cust_becky"),
        "Can I change my shipping address?",
        today=TODAY,
        now=NOW,
    )
    assert address.tools[0].payload["id"] == "address-change"
    assert "does not change the address" in address.template
    assert "packing" in address.template
    assert "start_return" not in store.calls
    assert facts_allowed(cancel.template, cancel.payload)
    assert facts_allowed(address.template, address.payload)
