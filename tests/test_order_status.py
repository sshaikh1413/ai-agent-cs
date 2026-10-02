"""Order status answers. No Claude and no Atlas."""

from datetime import date, datetime, timezone

from bookly_support.agent.checker import accept_draft, facts_allowed, unsupported_facts
from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.resolve import asks_order_status
from bookly_support.agent.return_agent import ReturnAgent
from bookly_support.agent.templates import order_status

from test_allowlist import NOW, TODAY, FakeStore, _order

PACKED = "It is being packed at the Bookly warehouse."
SHIPPED = "It left the Bookly warehouse this morning."
ON_THE_WAY = "It is on a truck between the warehouse and Memphis."
OUT_FOR_DELIVERY = "A driver has it on the route today in Memphis."


def _progress(order_id: str, title: str, status: str, detail: str) -> dict:
    return {
        "orderId": order_id,
        "title": title,
        "placedAt": datetime(2026, 10, 1, 9, tzinfo=timezone.utc),
        "deliveredAt": None,
        "status": status,
        "statusDetail": detail,
        "refundableCents": 1700,
        "paymentMethodId": "pm_becky_visa",
        "genre": "fiction",
    }


def _machine(orders: list[dict], customer_id: str = "cust_becky") -> tuple[FakeStore, Machine, Session]:
    store = FakeStore(orders, customer_id=customer_id)
    return store, Machine(store), Session(id="conv_status", customer_id=customer_id)


def test_status_phrases_are_not_return_or_refund_wording() -> None:
    for phrase in (
        "where is my order",
        "Where's my order?",
        "order status",
        "has it shipped",
        "is it out for delivery",
        "what's the status of BLY-44120",
        "What is the status of Klara and the Sun?",
    ):
        assert asks_order_status(phrase), phrase
    for phrase in (
        "I want to return a product",
        "card is fine",
        "the original payment method",
        "store credit",
        "changed my mind",
        "it arrived late",
        "who is the author",
        "what is it about",
    ):
        assert asks_order_status(phrase) is False, phrase


def test_one_in_progress_order_returns_the_stored_status() -> None:
    orders = [_progress("BLY-44120", "Klara and the Sun", "packing", PACKED)]
    store, machine, session = _machine(orders)
    for phrase in ("where is my order", "order status", "has it shipped", "is it out for delivery"):
        session = Session(id="conv_status", customer_id="cust_becky")
        turn = machine.step(session, phrase, today=TODAY, now=NOW)
        assert turn.step == "Step: order status"
        assert turn.intent == "order_status"
        assert turn.template == order_status(turn.tools[0].payload)
        assert "BLY-44120" in turn.template
        assert "Klara and the Sun" in turn.template
        assert "packing" in turn.template
        assert PACKED in turn.template
        assert "shipped" not in turn.template
        assert "out for delivery" not in turn.template
        assert turn.tools[0].payload["status"] == "packing"
        assert turn.tools[0].payload["statusDetail"] == PACKED
        assert facts_allowed(turn.template, turn.payload)
        assert turn.choices == []
        assert session.phase == "identify_order"
        assert session.order_id is None
    assert "start_return" not in store.calls
    assert "get_refund_options" not in store.calls


def test_two_in_progress_orders_ask_which() -> None:
    store, machine, session = _machine(
        [
            _progress("BLY-44120", "Klara and the Sun", "packing", PACKED),
            _progress("BLY-44121", "The Night Circus", "shipped", SHIPPED),
        ]
    )
    turn = machine.step(session, "where is my order", today=TODAY, now=NOW)
    assert turn.step == "Step: order status"
    assert "Which order?" in turn.template
    assert "BLY-44120" in turn.template
    assert "BLY-44121" in turn.template
    assert "Klara and the Sun" in turn.template
    assert "The Night Circus" in turn.template
    assert "packing" in turn.template
    assert "shipped" in turn.template
    assert PACKED in turn.template
    assert SHIPPED in turn.template
    assert [tool.name for tool in turn.tools] == ["list_recent_orders"]
    assert {choice.order_id for choice in turn.choices} == {"BLY-44120", "BLY-44121"}
    assert {choice.mark for choice in turn.choices} == {
        "Still on the way, packing",
        "Still on the way, shipped",
    }
    assert facts_allowed(turn.template, turn.payload)
    assert session.phase == "identify_order"
    assert session.order_id is None
    assert "start_return" not in store.calls


def test_a_named_id_returns_that_orders_status() -> None:
    _store, machine, session = _machine(
        [
            _progress("BLY-44120", "Klara and the Sun", "packing", PACKED),
            _progress("BLY-44121", "The Night Circus", "shipped", SHIPPED),
            _order("BLY-22018", "The Midnight Library", date(2026, 9, 24), date(2026, 9, 26), 1699),
        ]
    )
    turn = machine.step(session, "what's the status of BLY-44121", today=TODAY, now=NOW)
    assert turn.step == "Step: order status"
    assert [tool.name for tool in turn.tools] == ["get_order"]
    assert turn.tools[0].payload["orderId"] == "BLY-44121"
    assert turn.tools[0].payload["status"] == "shipped"
    assert turn.tools[0].payload["statusDetail"] == SHIPPED
    assert turn.template == (
        f"The Night Circus, order BLY-44121, is shipped. {SHIPPED}"
    )
    assert "Klara" not in turn.template
    assert "packing" not in turn.template
    assert session.phase == "identify_order"
    assert session.order_id is None

    delivered = machine.step(
        Session(id="conv_delivered", customer_id="cust_becky"),
        "what's the status of BLY-22018",
        today=TODAY,
        now=NOW,
    )
    assert "was delivered" in delivered.template
    assert "BLY-22018" in delivered.template
    assert "The Midnight Library" in delivered.template
    assert delivered.tools[0].payload["status"] == "delivered"
    assert facts_allowed(delivered.template, delivered.payload)


def test_a_draft_with_a_different_status_is_rejected() -> None:
    payload = {
        "results": [
            {
                "orderId": "BLY-44120",
                "title": "Klara and the Sun",
                "status": "packing",
                "statusDetail": PACKED,
            }
        ]
    }
    template = f"Klara and the Sun, order BLY-44120, is packing. {PACKED}"
    required = ["BLY-44120", "Klara and the Sun", "packing", PACKED]
    assert facts_allowed(template, payload)
    assert accept_draft(template, template, payload, required) == template

    wrong_status = f"Klara and the Sun, order BLY-44120, is shipped. {PACKED}"
    assert "shipped" in unsupported_facts(wrong_status, payload)
    assert accept_draft(wrong_status, template, payload, required) == template

    wrong_detail = "Klara and the Sun, order BLY-44120, is packing. It is sitting in Denver."
    assert any("denver" in item.lower() for item in unsupported_facts(wrong_detail, payload))
    assert accept_draft(wrong_detail, template, payload, required) == template

    wrong_id = f"Klara and the Sun, order BLY-99999, is packing. {PACKED}"
    assert any("BLY-99999" in item for item in unsupported_facts(wrong_id, payload))
    assert accept_draft(wrong_id, template, payload, required) == template


def test_a_status_question_does_not_start_a_return() -> None:
    midnight = _order("BLY-22018", "The Midnight Library", date(2026, 9, 24), date(2026, 9, 26), 1699)
    packed = _progress("BLY-44120", "Klara and the Sun", "packing", PACKED)
    store, machine, session = _machine([packed, midnight])

    status = machine.step(session, "where is my order", today=TODAY, now=NOW)
    assert status.step == "Step: order status"
    assert "packing" in status.template
    assert session.phase == "identify_order"
    assert session.order_id is None

    named = machine.step(session, "I want to return The Midnight Library", today=TODAY, now=NOW)
    assert session.phase == "ask_reason"
    assert session.order_id == "BLY-22018"
    assert "What made you want to send it back?" in named.template

    still = machine.step(session, "has it shipped", today=TODAY, now=NOW)
    assert still.step == "Step: order status"
    assert session.phase == "ask_reason"
    assert session.reason is None
    assert session.order_id == "BLY-22018"
    assert "packing" in still.template

    reason = machine.step(session, "changed my mind", today=TODAY, now=NOW)
    assert session.phase == "choose_destination"
    assert session.reason == "changed my mind"
    assert "start_return" not in store.calls

    during_choice = machine.step(session, "is it out for delivery", today=TODAY, now=NOW)
    assert during_choice.step == "Step: order status"
    assert session.phase == "choose_destination"
    assert session.destination is None
    assert "start_return" not in store.calls

    blocked = machine.step(
        Session(id="conv_blocked", customer_id="cust_becky"),
        "I want to return BLY-44120",
        today=TODAY,
        now=NOW,
    )
    assert blocked.step == "Step: which order"
    assert "has not been delivered" in blocked.template
    assert "packing" in blocked.template
    assert "past the" not in blocked.template
    assert "30-day" not in blocked.template
    assert "get_refund_options" not in [tool.name for tool in blocked.tools]
    assert "start_return" not in [tool.name for tool in blocked.tools]
    assert "start_return" not in store.calls


def test_card_is_fine_still_selects_the_visa_refund() -> None:
    midnight = _order("BLY-22018", "The Midnight Library", date(2026, 9, 24), date(2026, 9, 26), 1699)
    store, machine, session = _machine(
        [midnight, _progress("BLY-44120", "Klara and the Sun", "packing", PACKED)]
    )
    machine.step(session, "I want to return The Midnight Library", today=TODAY, now=NOW)
    machine.step(session, "changed my mind", today=TODAY, now=NOW)
    assert session.phase == "choose_destination"

    status = machine.step(session, "where is my order", today=TODAY, now=NOW)
    assert status.step == "Step: order status"
    assert session.phase == "choose_destination"
    assert session.destination is None
    assert "start_return" not in store.calls

    done = machine.step(session, "card is fine", today=TODAY, now=NOW)
    assert [tool.name for tool in done.tools] == ["start_return"]
    assert done.tools[0].payload["destination"] == "original_payment"
    assert "4242" in done.template
    assert session.destination == "original_payment"
    assert session.phase == "done"


def test_return_prompt_stays_on_a_delivered_order() -> None:
    class _Named(FakeStore):
        def get_customer(self, customer_id: str) -> dict:
            assert customer_id == self.customer_id
            return {"id": customer_id, "name": "Bob Hale", "email": "bob@example.com"}

        def latest_completed_return(self, customer_id: str) -> None:
            assert customer_id == self.customer_id
            return None

    store = _Named(
        [
            _progress("BLY-44123", "Beach Read", "out for delivery", OUT_FOR_DELIVERY),
            _order("BLY-33010", "A Gentleman in Moscow", date(2026, 9, 12), date(2026, 9, 28), 1800),
        ],
        customer_id="cust_bob",
    )
    info = ReturnAgent(store, object()).desk("cust_bob")  # type: ignore[arg-type]
    assert info.prompts[1] == "I want to return A Gentleman in Moscow"
    assert "Where is my order" in info.prompts
    assert any("status stored on that order" in line for line in info.can_help)
    assert "out for delivery · Beach Read" in info.sample_orders[0].summary


def test_on_the_way_detail_is_the_stored_sentence() -> None:
    _store, machine, session = _machine(
        [_progress("BLY-44122", "Educated", "on the way", ON_THE_WAY)],
        customer_id="cust_bob",
    )
    session.customer_id = "cust_bob"
    turn = machine.step(session, "where is my order", today=TODAY, now=NOW)
    assert turn.template == f"Educated, order BLY-44122, is on the way. {ON_THE_WAY}"
    assert facts_allowed(turn.template, turn.payload)
