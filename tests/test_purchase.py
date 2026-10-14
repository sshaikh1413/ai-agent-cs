"""Ordering a book Mara recommended. No Claude and no Atlas."""

from bookly_support.agent.checker import unsupported_facts
from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.resolve import stated_address, wants_to_buy
from bookly_support.agent.return_agent import confirmation_download

from test_allowlist import NOW, TODAY, FakeStore
from test_window_exception import _becky_orders

_CATALOG = [
    {"title": "Beach Read", "author": "Emily Henry", "genre": "romance", "priceCents": 1600},
    {"title": "Circe", "author": "Madeline Miller", "genre": "fantasy", "priceCents": 1700},
]


def _after_recommendation() -> tuple[FakeStore, Machine, Session]:
    store = FakeStore(_becky_orders(), catalog=_CATALOG)
    machine = Machine(store)
    session = Session(id="conv_buy", customer_id="cust_becky")
    session.recommended_title = "Beach Read"
    session.phase = "done"
    return store, machine, session


def test_order_the_recommended_book_confirms_then_places_it() -> None:
    store, machine, session = _after_recommendation()
    offer = machine.step(session, "I liked the Beach Road idea. Can i order one?", today=TODAY, now=NOW)
    assert session.phase == "purchase_confirm"
    assert offer.template.startswith("Absolutely! Beach Read")
    assert "ships free with 2-day delivery" in offer.template
    assert "Visa ending 4242" in offer.template
    assert "418 Linden Street" in offer.template
    assert offer.template.endswith("Does that look right?")
    assert "place_order" not in store.calls
    assert unsupported_facts(offer.template, offer.payload) == []

    placed = machine.step(session, "yes", today=TODAY, now=NOW)
    assert session.phase == "done"
    assert "Your order for Beach Read is placed" in placed.template
    assert "arrive in 2 business days" in placed.template
    assert "order confirmation is ready" in placed.template
    assert confirmation_download(placed, "cust_becky") is not None
    assert unsupported_facts(placed.template, placed.payload) == []


def test_a_new_address_is_confirmed_again_for_this_order_only() -> None:
    store, machine, session = _after_recommendation()
    machine.step(session, "can I order one?", today=TODAY, now=NOW)
    changed = machine.step(session, "send it to 500 Market Street, San Francisco, CA 94105 instead", today=TODAY, now=NOW)
    assert changed.template.startswith("Got it, I'll send it to 500 Market Street, San Francisco, CA 94105 instead.")
    assert changed.template.endswith("Shall I place the order?")
    assert session.phase == "purchase_confirm"
    placed = machine.step(session, "yes please", today=TODAY, now=NOW)
    assert placed.tools[0].payload["address"] == "500 Market Street, San Francisco, CA 94105"
    assert store.address != "500 Market Street, San Francisco, CA 94105"


def test_no_does_not_order() -> None:
    store, machine, session = _after_recommendation()
    machine.step(session, "can I order one?", today=TODAY, now=NOW)
    turn = machine.step(session, "no thanks", today=TODAY, now=NOW)
    assert turn.template.startswith("No problem, I haven't placed the order.")
    assert "place_order" not in store.calls


def test_a_second_yes_does_not_order_twice() -> None:
    store, machine, session = _after_recommendation()
    machine.step(session, "can I order one?", today=TODAY, now=NOW)
    first = machine.step(session, "yes", today=TODAY, now=NOW)
    session.phase = "purchase_confirm"
    again = machine.step(session, "yes", today=TODAY, now=NOW)
    assert first.tools[0].payload["orderId"] == again.tools[0].payload["orderId"]
    assert len(store.__dict__["placed_orders"]) == 1


def test_asking_to_order_without_a_book_asks_which() -> None:
    store = FakeStore(_becky_orders(), catalog=_CATALOG)
    machine = Machine(store)
    session = Session(id="conv_buy_which", customer_id="cust_becky")
    turn = machine.step(session, "I'd like to order a book", today=TODAY, now=NOW)
    assert turn.template == "Happy to! Which book would you like to order?"
    assert session.phase == "purchase_which"


def test_buy_phrases() -> None:
    assert wants_to_buy("Can I order one?")
    assert wants_to_buy("I'd like to buy Beach Read")
    assert not wants_to_buy("where is my order")
    assert not wants_to_buy("I'll take it")
    assert not wants_to_buy("can I get it on my Visa instead?")
    assert stated_address("send it to 500 Market Street, San Francisco, CA 94105 instead") == "500 Market Street, San Francisco, CA 94105"
