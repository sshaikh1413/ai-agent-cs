"""Mara sounds like a clerk: no echoed reasons, dollar amounts, emailed documents on a call,
and a book found from part of its title. No Claude and no Atlas."""

from bookly_support.agent.checker import accept_draft
from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.provider import ChatReply, OrderChoice, ParcelLabel, ReceiptDownload
from bookly_support.agent.reasons import reason_topic
from bookly_support.agent.resolve import partial_title_matches
from bookly_support.agent.templates import dollars, empathy_other, late_apology
from bookly_support.voice.desk import number_words, spoken_amounts, spoken_text

from test_allowlist import NOW, TODAY, FakeStore
from test_window_exception import _becky_orders


def _desk() -> tuple[FakeStore, Machine, Session]:
    store = FakeStore(_becky_orders())
    return store, Machine(store), Session(id="conv_natural", customer_id="cust_becky")


def test_the_reason_is_acknowledged_not_repeated() -> None:
    _store, machine, session = _desk()
    machine.step(session, "I want to return The Midnight Library", today=TODAY, now=NOW)
    turn = machine.step(session, "I didn't really like the genre", today=TODAY, now=NOW)
    assert turn.template.startswith("I'm sorry The Midnight Library wasn't your kind of book.")
    assert "genre" not in turn.template
    assert "I hear you" not in turn.template
    assert "Do not repeat, quote, or paraphrase their sentence" in turn.instruction


def test_each_kind_of_reason_gets_its_own_line() -> None:
    assert reason_topic("the pages were torn") == "damaged"
    assert reason_topic("you sent the wrong edition") == "wrong_book"
    assert reason_topic("I already have it") == "duplicate"
    assert reason_topic("changed my mind") == "changed_mind"
    assert reason_topic("so boring") == "not_for_me"
    assert reason_topic("it arrived late") == "late"
    assert "reached you in that shape" in empathy_other("Circe", "damaged")
    assert "wasn't the book you were expecting" in empathy_other("Circe", "wrong_book")
    assert empathy_other("Circe", None) == "I'm sorry Circe didn't work out. Thanks for letting me know."
    assert late_apology("Circe", "it was a birthday gift") == (
        "I'm sorry Circe arrived late. I know it was meant as a birthday gift, and that's a real letdown."
    )
    assert late_apology("Circe", "too slow") == "I'm sorry Circe arrived late."


def test_amounts_are_dollars_in_the_chat() -> None:
    _store, machine, session = _desk()
    machine.step(session, "I want to return Circe", today=TODAY, now=NOW)
    turn = machine.step(session, "changed my mind", today=TODAY, now=NOW)
    assert "$17.00" in turn.template
    assert dollars("15.99") == "$15.99"
    assert dollars("$15.99") == "$15.99"


def test_amounts_and_card_digits_are_spoken_as_words() -> None:
    assert number_words(16) == "sixteen"
    assert number_words(1299) == "one thousand two hundred ninety-nine"
    assert spoken_amounts("$16.99 back on the Visa ending 4242") == (
        "sixteen dollars and ninety-nine cents back on the Visa ending in 4 2 4 2"
    )
    assert spoken_amounts("store credit for 15.99.") == "store credit for fifteen dollars and ninety-nine cents."
    assert spoken_amounts("$1.01") == "one dollar and one cent"
    assert spoken_amounts("$20") == "twenty dollars"


def _reply(text: str, *, receipt: bool, label: bool) -> ChatReply:
    return ChatReply(
        reply=text,
        intent="return_refund",
        step="Step: receipt and label",
        receipt=ReceiptDownload(receipt_id="rcpt_ab12", url="/api/receipts/rcpt_ab12") if receipt else None,
        label=ParcelLabel(label_id="lbl_ab12", url="/api/labels/lbl_ab12") if label else None,
    )


def test_a_call_says_the_receipt_and_label_were_emailed() -> None:
    both = _reply(
        "Your return is complete. Receipt rcpt_ab12 for Piranesi is $15.99 in store credit. "
        "The receipt and the parcel label are ready to download. Anything else I can help with?",
        receipt=True,
        label=True,
    )
    assert spoken_text(both) == (
        "Your return is complete. The refund for Piranesi is fifteen dollars and ninety-nine cents "
        "in store credit. I've emailed you your return confirmation receipt and shipping label. "
        "Once we receive the book, we'll process your refund. Anything else I can help with?"
    )
    receipt_only = _reply(
        "Your return is complete. Receipt rcpt_ab12 for Circe is $17.00 back on the Visa ending 4242. "
        "It's ready to download. Anything else I can help with?",
        receipt=True,
        label=False,
    )
    spoken = spoken_text(receipt_only)
    assert "I've emailed you your return confirmation receipt." in spoken
    assert "shipping label" not in spoken
    assert "download" not in spoken
    assert "rcpt_" not in spoken
    drafted = _reply(
        "Your return is complete. Your receipt is rcpt_ab12. Do you need anything else?",
        receipt=True,
        label=False,
    )
    assert spoken_text(drafted) == (
        "Your return is complete. I've emailed you your return confirmation receipt. "
        "Once we receive the book, we'll process your refund. Do you need anything else?"
    )
    plain = _reply("Which book do you want to return?", receipt=False, label=False)
    assert spoken_text(plain) == "Which book do you want to return?"


def test_part_of_a_title_finds_the_book() -> None:
    orders = [{"title": t} for t in ("The Night Circus", "Mexican Gothic", "The Midnight Library", "Piranesi")]
    found = lambda text: [o["title"] for o in partial_title_matches(text, orders)]  # noqa: E731
    assert found("it was something gothic") == ["Mexican Gothic"]
    assert found("the Mexican one") == ["Mexican Gothic"]
    assert found("the midnight one") == ["The Midnight Library"]
    assert found("Piranessi") == ["Piranesi"]
    assert found("I ordered it last night") == []
    assert found("I want to return a book") == []

    _store, machine, session = _desk()
    turn = machine.step(session, "I want to return something gothic", today=TODAY, now=NOW)
    assert session.order_id == "BLY-22044"
    assert "Mexican Gothic" in turn.template

    _store, machine, session = _desk()
    machine.step(session, "I want to return a book", today=TODAY, now=NOW)
    machine.step(session, "the midnight one", today=TODAY, now=NOW)
    assert session.order_id == "BLY-22018"


def test_the_customers_name_is_not_an_unsupported_fact() -> None:
    payload = {"results": [{"orderId": "BLY-22018", "title": "The Midnight Library"}]}
    draft = "Hi Becky, The Midnight Library is the one."
    assert accept_draft(draft, "TEMPLATE", payload, [], customer_name="Becky Alvarez") == draft
    assert accept_draft(draft.replace("Becky", "Sarah"), "TEMPLATE", payload, [], customer_name="Becky Alvarez") == "TEMPLATE"


def test_choice_dates_are_spoken_without_order_numbers() -> None:
    reply = ChatReply(
        reply="Which book do you want to return?",
        intent="return_refund",
        step="Step: which order",
        choices=[OrderChoice(order_id="BLY-22044", title="Mexican Gothic", mark="Delivered", placed="September 30")],
    )
    assert spoken_text(reply) == "Which book do you want to return? Mexican Gothic, ordered September 30."


def test_a_leading_order_number_is_dropped_on_a_call() -> None:
    from bookly_support.voice.desk import unspoken_ids

    assert unspoken_ids("BLY-44121 is The Night Circus. It's shipped.") == "The Night Circus. It's shipped."


def test_every_amount_has_a_dollar_sign() -> None:
    from bookly_support.agent.templates import dollar_signs

    assert dollar_signs("I can give you 15.99 in store credit for Piranesi.") == (
        "I can give you $15.99 in store credit for Piranesi."
    )
    assert dollar_signs("$15.99 is already right.") == "$15.99 is already right."
    assert dollar_signs("16.99 or 1,250.00") == "$16.99 or $1,250.00"
    assert dollar_signs("a 20% code, order BLY-22018, August 10, 2026") == "a 20% code, order BLY-22018, August 10, 2026"


class _NoDollarSigns:
    """Claude sometimes writes "15.99" without the sign. The desk adds it."""

    def phrase(self, turn, message, customer_name=None, memory=None):
        del message, customer_name, memory
        return turn.template.replace("$", "")


def test_a_draft_without_dollar_signs_gets_them() -> None:
    from datetime import date

    from bookly_support.agent.provider import ChatRequest
    from bookly_support.agent.return_agent import ReturnAgent

    from test_allowlist import _order
    from test_voice_call import _Sessions

    agent = ReturnAgent(
        _Sessions([_order("BLY-22002", "Circe", date(2026, 9, 11), date(2026, 9, 15), 1700)]),
        _NoDollarSigns(),
    )
    first = agent.reply(ChatRequest(message="I want to return Circe", customer_id="cust_becky"))
    offer = agent.reply(
        ChatRequest(message="changed my mind", conversation_id=first.conversation_id, customer_id="cust_becky")
    )
    assert "$17.00" in offer.reply
    assert " 17.00" not in offer.reply.replace("$17.00", "")


def test_a_horror_reply_follows_what_they_said_about_the_scares() -> None:
    _store, machine, session = _desk()
    machine.step(session, "I want to return Mexican Gothic", today=TODAY, now=NOW)
    turn = machine.step(session, "it was way too scary", today=TODAY, now=NOW)
    assert "Mexican Gothic was too scary for you. Horror isn't for everyone." in turn.template
    from bookly_support.agent.templates import empathy_horror

    assert empathy_horror("Mexican Gothic", {"title": "Beach Read"}, "negative", "too_scary") == (
        "I'm really sorry Mexican Gothic was too scary for you. Horror isn't for everyone. "
        "If you'd like something gentler, try Beach Read."
    )
    assert "not scary" not in turn.template
    assert "matching what they said" in turn.instruction

    _store, machine, session = _desk()
    machine.step(session, "I want to return Mexican Gothic", today=TODAY, now=NOW)
    turn = machine.step(session, "it wasn't scary at all", today=TODAY, now=NOW)
    assert "Mexican Gothic wasn't scary enough." in turn.template
    assert "too scary" not in turn.template

    assert reason_topic("I don't like horror") == "not_for_me"
    assert reason_topic("gave me nightmares") == "too_scary"
