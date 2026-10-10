"""Readers remember a title or roughly when, not an order number, and say things once.

No Claude and no Atlas. Today is October 1, 2026 in these tests.
"""

from datetime import date

from bookly_support.agent.checker import unsupported_facts
from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.resolve import asks_for_agent, stated_reason
from bookly_support.agent.window import ordered_window

from test_allowlist import ASK_TITLE_OR_DATE, NOW, TODAY, FakeStore
from test_window_exception import _becky_orders

HANDOFF = "Of course. One moment, please, and I'll connect you with one of our agents."


def _desk() -> tuple[FakeStore, Machine, Session]:
    store = FakeStore(_becky_orders())
    return store, Machine(store), Session(id="conv_recall", customer_id="cust_becky")


def test_a_return_with_no_book_asks_for_the_title_or_the_date_first() -> None:
    store, machine, session = _desk()
    asked = machine.step(session, "I want to return a product", today=TODAY, now=NOW)
    assert asked.template == ASK_TITLE_OR_DATE
    assert asked.read_choices is False
    assert len(asked.choices) == 6
    assert session.asked_which is True
    assert "get_order" not in store.calls

    listed = machine.step(session, "I don't remember", today=TODAY, now=NOW)
    assert listed.template == "Which book do you want to return?"
    assert listed.read_choices is True
    assert [c.placed for c in listed.choices][2:] == ["September 30", "September 24", "September 11", "August 10"]

    picked = machine.step(session, "Circe", today=TODAY, now=NOW)
    assert session.order_id == "BLY-22002"
    assert "What made you want to send it back?" in picked.template


def test_the_title_answers_the_question_without_a_list() -> None:
    _store, machine, session = _desk()
    machine.step(session, "I want to return a book", today=TODAY, now=NOW)
    picked = machine.step(session, "The Midnight Library", today=TODAY, now=NOW)
    assert session.order_id == "BLY-22018"
    assert picked.choices == []


def test_when_they_ordered_it_finds_the_book() -> None:
    _store, machine, session = _desk()
    machine.step(session, "I want to return a book", today=TODAY, now=NOW)
    picked = machine.step(session, "I ordered it on September 24th", today=TODAY, now=NOW)
    assert session.order_id == "BLY-22018"
    assert "What made you want to send it back?" in picked.template


def test_a_date_with_several_orders_lists_only_those() -> None:
    _store, machine, session = _desk()
    turn = machine.step(session, "I want to return a book I ordered last month", today=TODAY, now=NOW)
    assert turn.template == "I've got more than one order from around then. Which one is it?"
    assert [c.title for c in turn.choices] == ["Mexican Gothic", "The Midnight Library", "Circe"]
    assert turn.read_choices is True
    assert session.order_id is None


def test_a_date_with_no_order_says_so_and_lists_everything() -> None:
    _store, machine, session = _desk()
    turn = machine.step(session, "return the book I ordered two weeks ago", today=TODAY, now=NOW)
    assert turn.template.startswith("I don't see an order from around then.")
    assert len(turn.choices) == 6
    assert session.order_id is None


def test_a_reason_in_the_same_sentence_is_not_asked_again() -> None:
    store, machine, session = _desk()
    turn = machine.step(
        session, "I want to return The Midnight Library because it was boring", today=TODAY, now=NOW
    )
    assert session.order_id == "BLY-22018"
    assert session.reason == "it was boring"
    assert session.reason_kind == "other"
    assert "What made you want to send it back?" not in turn.template
    assert session.phase in {"choose_destination", "empathy"}
    assert "start_return" not in store.calls


def test_past_window_says_when_ordered_and_how_many_days_past() -> None:
    _store, machine, session = _desk()
    turn = machine.step(session, "I want to return Piranesi", today=TODAY, now=NOW)
    assert session.phase == "exception_why"
    assert "You ordered Piranesi" in turn.template
    assert "on August 10, and it was delivered August 15" in turn.template
    # Delivered August 15, so the 30-day window closed September 14: 17 days ago.
    assert "That's 17 days past our 30-day return window" in turn.template
    assert "What is the reason for the return?" in turn.template
    assert "store credit" not in turn.template.lower()
    assert unsupported_facts(turn.template, turn.payload) == []


def test_past_window_with_a_reason_goes_straight_to_the_offer() -> None:
    store, machine, session = _desk()
    turn = machine.step(session, "I want to return Piranesi because the pages were torn", today=TODAY, now=NOW)
    assert session.phase == "exception_offer"
    assert session.reason == "the pages were torn"
    assert "17 days past our 30-day return window" in turn.template
    assert "What is the reason for the return?" not in turn.template
    assert "store credit exception for $15.99" in turn.template
    assert unsupported_facts(turn.template, turn.payload) == []
    assert "start_return" not in store.calls


def test_asking_for_a_person_hands_off_at_any_step() -> None:
    for phrase in ("can I speak to a representative", "operator", "agent", "let me talk to a real person"):
        store, machine, session = _desk()
        turn = machine.step(session, phrase, today=TODAY, now=NOW)
        assert turn.template == HANDOFF, phrase
        assert turn.intent == "handoff", phrase
        assert turn.step == "Step: connect to an agent", phrase
        assert store.calls == [], phrase

    _store, machine, session = _desk()
    machine.step(session, "I want to return Circe", today=TODAY, now=NOW)
    mid = machine.step(session, "customer service please", today=TODAY, now=NOW)
    assert mid.template == HANDOFF
    assert session.phase == "ask_reason"
    assert session.order_id == "BLY-22002"


def test_a_question_about_mara_is_not_a_handoff() -> None:
    assert asks_for_agent("are you a human?") is False
    assert asks_for_agent("are you an agent?") is False
    assert asks_for_agent("where is my order") is False


def test_closed_phrases_for_dates_and_reasons() -> None:
    assert ordered_window("last month", TODAY) == (date(2026, 9, 1), date(2026, 9, 30))
    assert ordered_window("in August", TODAY) == (date(2026, 8, 1), date(2026, 8, 31))
    assert ordered_window("sept 20th", TODAY) == (date(2026, 9, 18), date(2026, 9, 22))
    assert ordered_window("I want to return a product", TODAY) is None
    assert stated_reason("return Circe because it was boring") == "it was boring"
    assert stated_reason("return Circe") is None


def test_a_yearless_date_must_be_in_the_payload() -> None:
    payload = {"results": [{"placedAt": "2026-08-10T06:00:00Z"}]}
    assert unsupported_facts("You ordered it on August 10.", payload) == []
    assert unsupported_facts("You ordered it on August 12.", payload) == ["August 12"]


COULD_NOT_FIND = "I couldn't find that book on your account. Would you like me to read your recent orders?"


def test_a_call_offers_to_read_the_list_when_the_book_is_not_found() -> None:
    store, machine, session = _desk()
    asked = machine.step(session, "I want to return a book", today=TODAY, now=NOW, voice=True)
    assert asked.template == ASK_TITLE_OR_DATE
    assert asked.read_choices is False

    missed = machine.step(session, "the one with the dragon on the cover", today=TODAY, now=NOW, voice=True)
    assert missed.template == COULD_NOT_FIND
    assert missed.read_choices is False
    assert session.offered_list is True
    assert "get_order" not in store.calls

    read = machine.step(session, "yes please", today=TODAY, now=NOW, voice=True)
    assert read.template == "Which book do you want to return?"
    assert read.read_choices is True
    assert len(read.choices) == 6
    assert session.offered_list is False

    picked = machine.step(session, "Circe", today=TODAY, now=NOW, voice=True)
    assert session.order_id == "BLY-22002"
    assert "What made you want to send it back?" in picked.template


def test_a_call_can_say_no_to_the_list_and_name_the_book() -> None:
    _store, machine, session = _desk()
    machine.step(session, "I want to return a book", today=TODAY, now=NOW, voice=True)
    machine.step(session, "the blue one", today=TODAY, now=NOW, voice=True)
    again = machine.step(session, "no", today=TODAY, now=NOW, voice=True)
    assert again.template == "Okay. What's the title, or about when you ordered it?"
    assert again.read_choices is False
    machine.step(session, "Mexican Gothic", today=TODAY, now=NOW, voice=True)
    assert session.order_id == "BLY-22044"


def test_a_call_with_no_order_on_that_date_offers_the_list() -> None:
    _store, machine, session = _desk()
    turn = machine.step(session, "return the book I ordered two weeks ago", today=TODAY, now=NOW, voice=True)
    assert turn.template == "I don't see an order from around then. Would you like me to read your recent orders?"
    assert turn.read_choices is False
    assert session.offered_list is True


def test_a_call_reads_the_list_when_they_do_not_remember() -> None:
    _store, machine, session = _desk()
    machine.step(session, "I want to return a book", today=TODAY, now=NOW, voice=True)
    read = machine.step(session, "I don't remember", today=TODAY, now=NOW, voice=True)
    assert read.template == "Which book do you want to return?"
    assert read.read_choices is True


def test_the_chat_still_lists_the_books_after_a_miss() -> None:
    _store, machine, session = _desk()
    machine.step(session, "I want to return a book", today=TODAY, now=NOW)
    listed = machine.step(session, "the one with the dragon on the cover", today=TODAY, now=NOW)
    assert listed.template == "Which book do you want to return?"
    assert listed.read_choices is True
    assert session.offered_list is False


def test_no_right_after_the_book_is_named_means_the_wrong_book() -> None:
    store, machine, session = _desk()
    machine.step(session, "I want to return The Midnight Library", today=TODAY, now=NOW, voice=True)
    assert session.order_id == "BLY-22018"
    turn = machine.step(session, "no", today=TODAY, now=NOW, voice=True)
    assert turn.template == "Sorry about that. What's the title, or about when you ordered it?"
    assert turn.read_choices is False
    assert session.order_id is None
    assert session.reason is None
    assert session.phase == "identify_order"
    machine.step(session, "Circe", today=TODAY, now=NOW, voice=True)
    assert session.order_id == "BLY-22002"
    assert "start_return" not in store.calls
