"""Found it cheaper elsewhere: offer a price match before a return. No Claude and no Atlas."""

from bookly_support.agent.checker import unsupported_facts
from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.reasons import reason_topic
from bookly_support.agent.resolve import named_store, quoted_price

from test_allowlist import NOW, TODAY, FakeStore
from test_window_exception import _becky_orders


def _at_reason() -> tuple[FakeStore, Machine, Session]:
    store = FakeStore(_becky_orders())
    machine = Machine(store)
    session = Session(id="conv_match", customer_id="cust_becky")
    machine.step(session, "I want to return The Midnight Library", today=TODAY, now=NOW)
    return store, machine, session


def test_cheaper_elsewhere_offers_a_price_match_first() -> None:
    store, machine, session = _at_reason()
    offer = machine.step(session, "I found it cheaper somewhere else", today=TODAY, now=NOW)
    assert session.phase == "price_match_offer"
    assert offer.step == "Step: price match offer"
    assert "would you like a price match instead?" in offer.template
    # A lower price is good news for the reader: no apology.
    assert offer.template.startswith("Nice find!")
    assert "sorry" not in offer.template.lower()
    assert "do not apologize" in offer.instruction
    assert "Visa" not in offer.template
    assert "get_refund_options" not in store.calls


def test_yes_asks_for_the_price_and_store_then_refunds_the_difference() -> None:
    store, machine, session = _at_reason()
    machine.step(session, "I found it cheaper somewhere else", today=TODAY, now=NOW)
    ask = machine.step(session, "yes please", today=TODAY, now=NOW)
    assert ask.template == "Great. What price did you find, and at which store?"
    assert session.phase == "price_match_details"

    store_only = machine.step(session, "Barnes & Noble", today=TODAY, now=NOW)
    assert store_only.template == "What price did you see at Barnes & Noble?"

    done = machine.step(session, "$12.99", today=TODAY, now=NOW)
    assert done.template == (
        "Great news! I checked Barnes & Noble, and I see The Midnight Library there for $12.99. "
        "I'll go ahead and refund the $4.00 difference to your Visa ending 4242. "
        "Anything else I can do for you?"
    )
    assert [tool.name for tool in done.tools] == ["check_competitor_price", "issue_price_match"]
    assert done.tools[0].payload["simulated"] is True
    assert session.phase == "done"
    assert "start_return" not in store.calls
    assert unsupported_facts(done.template, done.payload) == []


def test_price_and_store_in_one_answer_skip_the_questions() -> None:
    store, machine, session = _at_reason()
    machine.step(session, "I found it cheaper at Target", today=TODAY, now=NOW)
    done = machine.step(session, "yes, it was 13.50", today=TODAY, now=NOW)
    assert "I checked Target" in done.template
    assert "$3.49 difference" in done.template
    assert store.calls.count("issue_price_match") == 1


def test_no_goes_to_the_usual_refund_question() -> None:
    store, machine, session = _at_reason()
    machine.step(session, "I found it cheaper somewhere else", today=TODAY, now=NOW)
    refund = machine.step(session, "no thanks", today=TODAY, now=NOW)
    assert session.phase == "choose_destination"
    assert refund.template.startswith("No problem. I can put $16.99 for The Midnight Library")
    assert "issue_price_match" not in store.calls


def test_a_price_that_is_not_lower_cannot_be_matched() -> None:
    store, machine, session = _at_reason()
    machine.step(session, "I found it cheaper somewhere else", today=TODAY, now=NOW)
    machine.step(session, "yes", today=TODAY, now=NOW)
    turn = machine.step(session, "$18.00 at Amazon", today=TODAY, now=NOW)
    assert turn.template.startswith(
        "I see The Midnight Library at Amazon for $18.00, which isn't lower than the $16.99 you paid, "
        "so I can't match it."
    )
    assert session.phase == "choose_destination"
    assert "Visa ending 4242" in turn.template


def test_price_and_store_phrases() -> None:
    assert reason_topic("I found it cheaper somewhere else") == "cheaper_elsewhere"
    assert reason_topic("Amazon has a better price") == "cheaper_elsewhere"
    assert quoted_price("it was $12.99") == 1299
    assert quoted_price("12 bucks") == 1200
    assert quoted_price("yes") is None
    assert named_store("at barnes and noble") == "Barnes & Noble"
    assert named_store("I saw it at Joe's Books") == "Joe's Books"


def _past_window_offer() -> tuple[FakeStore, Machine, Session]:
    store = FakeStore(_becky_orders())
    machine = Machine(store)
    session = Session(id="conv_match_late", customer_id="cust_becky")
    machine.step(session, "I want to return Piranesi", today=TODAY, now=NOW)
    assert session.phase == "exception_why"
    return store, machine, session


def test_past_the_window_cheaper_elsewhere_offers_a_price_match() -> None:
    store, machine, session = _past_window_offer()
    offer = machine.step(session, "I found it cheaper somewhere else", today=TODAY, now=NOW)
    assert session.phase == "price_match_offer"
    assert offer.template.startswith("Nice find!")
    assert "store credit" not in offer.template

    machine.step(session, "yes", today=TODAY, now=NOW)
    done = machine.step(session, "$11.00 at Target", today=TODAY, now=NOW)
    assert "refund the $4.99 difference" in done.template
    assert session.phase == "done"
    assert session.exception is False
    # They keep the book: a later "yes" does not write the store-credit return.
    machine.step(session, "yes", today=TODAY, now=NOW)
    assert "start_return" not in store.calls


def test_past_the_window_no_to_a_price_match_goes_back_to_store_credit_only() -> None:
    store, machine, session = _past_window_offer()
    machine.step(session, "I found it cheaper somewhere else", today=TODAY, now=NOW)
    back = machine.step(session, "no thanks", today=TODAY, now=NOW)
    assert session.phase == "exception_offer"
    assert back.template.startswith("No problem. I can make a one-time store credit exception for $15.99")
    assert "Visa" not in back.template
    assert "start_return" not in store.calls


def test_past_the_window_with_the_reason_up_front_offers_a_price_match() -> None:
    _store, machine, session = _past_window_offer()
    fresh = Session(id="conv_match_late_2", customer_id="cust_becky")
    turn = machine.step(fresh, "I want to return Piranesi because I found it cheaper at Target", today=TODAY, now=NOW)
    assert fresh.phase == "price_match_offer"
    assert "past our 30-day return window" in turn.template
    assert "Nice find! Before you send Piranesi back" in turn.template


def test_a_book_on_its_way_found_cheaper_does_not_repeat_itself() -> None:
    store = FakeStore(_becky_orders())
    machine = Machine(store)
    session = Session(id="conv_match_transit", customer_id="cust_becky")
    turn = machine.step(session, "I want to return The Night Circus because I found it cheaper elsewhere", today=TODAY, now=NOW)
    assert session.phase == "price_match_offer"
    assert turn.template == (
        "The Night Circus, order BLY-44121, hasn't been delivered yet. It's shipped. "
        "Nice find! Before you send The Night Circus back, would you like a price match instead? "
        "You'd keep the book, and I'd refund the difference."
    )
