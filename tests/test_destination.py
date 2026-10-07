"""Refund destination wording. No Claude and no Atlas.

Closed phrases are matched in code. Any other wording is Claude's label (the
golden set stands in for it here), and the machine only acts on a destination
while it is asking for one.
"""

from datetime import date

from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.resolve import destination_choice, explicit_destination
from golden_understanding import GOLDEN, key
from test_allowlist import NOW, TODAY, FakeStore, _order

ORIGINAL = (
    "card is fine",
    "visa is fine",
    "the card works",
    "put it back on the card",
    "original payment",
    "Visa",
    "credit card",
)
STORE = (
    "store credit is fine",
    "credit on my account",
    "store credit",
)
NEITHER = ("blue", "whatever")


def test_closed_phrases_still_select_a_destination() -> None:
    assert explicit_destination("original payment") == "original_payment"
    assert explicit_destination("Visa") == "original_payment"
    assert explicit_destination("credit card") == "original_payment"
    assert explicit_destination("store credit") == "store_credit"
    assert destination_choice("the original payment method") == "original_payment"
    assert destination_choice("store credit") == "store_credit"


def test_open_wording_is_left_to_claude_not_the_closed_phrases() -> None:
    assert explicit_destination("card is fine") is None
    assert destination_choice("card is fine") is None
    assert destination_choice("credit on my account") is None
    assert GOLDEN[key("card is fine")]["destination"] == "original_payment"
    assert GOLDEN[key("credit on my account")]["destination"] == "store_credit"


def test_each_wording_selects_its_destination_in_the_machine() -> None:
    for phrase in ORIGINAL:
        store, machine, session = _ready()
        done = machine.step(session, phrase, today=TODAY, now=NOW)
        assert done.tools[0].payload["destination"] == "original_payment", phrase
    for phrase in STORE:
        store, machine, session = _ready()
        done = machine.step(session, phrase, today=TODAY, now=NOW)
        assert done.tools[0].payload["destination"] == "store_credit", phrase


def test_unrelated_words_do_not_start_the_return_and_card_is_fine_does() -> None:
    store, machine, session = _ready()
    for phrase in NEITHER:
        turn = machine.step(session, phrase, today=TODAY, now=NOW)
        assert turn.step == "Step: Visa or store credit"
        assert session.phase == "choose_destination"
        assert session.destination is None
        assert "start_return" not in store.calls

    done = machine.step(session, "card is fine", today=TODAY, now=NOW)
    assert [tool.name for tool in done.tools] == ["start_return"]
    assert done.tools[0].payload["destination"] == "original_payment"
    assert session.destination == "original_payment"
    assert session.phase == "done"


def test_credit_on_my_account_selects_store_credit() -> None:
    store, machine, session = _ready()
    done = machine.step(session, "credit on my account", today=TODAY, now=NOW)
    assert store.calls.count("start_return") == 1
    assert done.tools[0].payload["destination"] == "store_credit"
    assert session.destination == "store_credit"


def test_credit_card_stays_the_original_payment() -> None:
    store, machine, session = _ready()
    done = machine.step(session, "credit card", today=TODAY, now=NOW)
    assert store.calls.count("start_return") == 1
    assert done.tools[0].payload["destination"] == "original_payment"


def _ready() -> tuple[FakeStore, Machine, Session]:
    store = FakeStore(
        [
            _order(
                "BLY-22018",
                "The Midnight Library",
                date(2026, 9, 24),
                date(2026, 9, 26),
                1699,
            )
        ]
    )
    machine = Machine(store)
    session = Session(id="conv_destination", customer_id="cust_becky")
    machine.step(session, "I want to return The Midnight Library", today=TODAY, now=NOW)
    machine.step(session, "changed my mind", today=TODAY, now=NOW)
    assert session.phase == "choose_destination"
    assert "start_return" not in store.calls
    return store, machine, session
