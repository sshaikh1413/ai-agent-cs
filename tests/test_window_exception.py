"""Too late, then a store-credit exception. No Claude and no Atlas."""

from datetime import date, datetime, timezone

from bookly_support.agent.checker import accept_draft, unsupported_facts
from bookly_support.agent.label_pdf import CARRIER_NAME, render_parcel_label
from golden_understanding import GOLDEN, key
from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.queries import get_label
from bookly_support.agent.resolve import accepts_store_credit_exception
from bookly_support.agent.return_agent import label_download, receipt_download

from test_allowlist import NOW, TODAY, FakeStore, _order
from test_demo_reset import _Collection, _Database, _copy
from bookly_support.agent.reset import reset_bookly_demo

REASON = "The pages were falling out"
ADDRESS_LINES = ["418 Linden Street", "Oakland, CA 94607"]


def _store() -> FakeStore:
    packing = {
        "orderId": "BLY-44120",
        "title": "Klara and the Sun",
        "placedAt": datetime(2026, 10, 1, 14, tzinfo=timezone.utc),
        "status": "packing",
        "refundableCents": 1700,
        "paymentMethodId": "pm_becky_visa",
    }
    return FakeStore(
        [
            _order("BLY-18440", "Piranesi", date(2026, 8, 10), date(2026, 8, 15), 1599, "fantasy"),
            _order("BLY-22018", "The Midnight Library", date(2026, 9, 24), date(2026, 9, 26), 1699),
            packing,
        ]
    )


def _session() -> Session:
    return Session(id="conv_window", customer_id="cust_becky")


def test_too_late_lists_every_recent_order_with_its_mark() -> None:
    store = _store()
    turn = Machine(store).step(_session(), "Is it too late to return a book?", today=TODAY, now=NOW)
    assert [tool.name for tool in turn.tools] == ["list_recent_orders"]
    assert "start_return" not in store.calls
    assert "get_order" not in store.calls
    assert turn.step == "Step: which book"
    assert "Piranesi" in turn.template
    assert "The Midnight Library" in turn.template
    assert "Klara and the Sun" in turn.template
    assert "BLY-44120" in turn.template
    assert "Delivered and past the 30-day window" in turn.template
    assert "Delivered and inside the 30-day window" in turn.template
    assert "Still on the way, packing" in turn.template
    assert "August 15, 2026" in turn.template
    assert "September 26, 2026" in turn.template
    assert unsupported_facts(turn.template, turn.payload) == []
    assert [choice.order_id for choice in turn.choices] == [
        order["orderId"] for order in turn.tools[0].payload["orders"]
    ]
    assert [choice.mark for choice in turn.choices] == [
        order["mark"] for order in turn.tools[0].payload["orders"]
    ]
    marks = {order["title"]: order["mark"] for order in turn.tools[0].payload["orders"]}
    assert marks == {
        "Piranesi": "Delivered and past the 30-day window",
        "The Midnight Library": "Delivered and inside the 30-day window",
        "Klara and the Sun": "Still on the way, packing",
    }
    windows = {order["title"]: order.get("window") for order in turn.tools[0].payload["orders"]}
    assert windows["Piranesi"] == "past"
    assert windows["The Midnight Library"] == "inside"
    assert "window" not in turn.tools[0].payload["orders"][2]
    shipped = turn.template.replace("packing", "shipped")
    assert "shipped" in unsupported_facts(shipped, turn.payload)
    assert accept_draft(shipped, turn.template, turn.payload, turn.required) == turn.template
    invented = f"{turn.template} The Silent Patient is still on the way."
    assert any("Silent" in problem for problem in unsupported_facts(invented, turn.payload))
    assert accept_draft(invented, turn.template, turn.payload, turn.required) == turn.template


def test_old_title_asks_why_and_yes_writes_one_store_credit_exception() -> None:
    store = _store()
    machine = Machine(store)
    session = _session()
    machine.step(session, "Is it too late to return a book?", today=TODAY, now=NOW)

    why = machine.step(session, "Piranesi", today=TODAY, now=NOW)
    assert session.phase == "exception_why"
    assert session.order_id == "BLY-18440"
    assert why.step == "Step: what happened"
    assert "past the 30 days" in why.template
    assert "cannot go back on the Visa" in why.template
    assert "store credit" not in why.template.lower()
    assert "4242" not in why.template
    assert "What happened with it?" in why.template
    assert "get_refund_options" not in store.calls
    assert "start_return" not in store.calls
    assert unsupported_facts(why.template, why.payload) == []

    offer = machine.step(session, REASON, today=TODAY, now=NOW)
    assert session.phase == "exception_offer"
    assert session.reason == REASON
    assert session.reason_kind == "other"
    assert "store credit" in offer.template
    assert "15.99" in offer.template
    assert "Piranesi" in offer.template
    assert "Visa" not in offer.template
    assert "4242" not in offer.template
    assert "start_return" not in store.calls
    assert unsupported_facts(offer.template, offer.payload) == []
    visa = "I'll refund the Visa for 15.99 on Piranesi."
    assert accept_draft(visa, offer.template, offer.payload, offer.required) == offer.template
    fedex = f"{offer.template} I sent it by FedEx."
    assert accept_draft(fedex, offer.template, offer.payload, offer.required) == offer.template

    held = machine.step(session, "card is fine", today=TODAY, now=NOW)
    assert session.phase == "exception_offer"
    assert session.destination is None
    assert "start_return" not in store.calls
    assert "store credit" in held.template
    assert accepts_store_credit_exception("card is fine") is False
    assert accepts_store_credit_exception("yes") is True
    assert accepts_store_credit_exception("I will take it") is True

    done = machine.step(session, "yes", today=TODAY, now=NOW)
    assert store.calls.count("start_return") == 1
    assert done.step == "Step: receipt and label"
    assert done.tools[0].payload["destination"] == "store_credit"
    assert done.tools[0].payload["exception"] is True
    assert "15.99" in done.template
    assert "store credit" in done.template
    assert done.tools[0].payload["receiptId"] in done.template
    assert "parcel label" in done.template
    receipt = receipt_download(done, "cust_becky")
    label = label_download(done, "cust_becky")
    assert receipt is not None and receipt.receipt_id == "rcpt_fixed"
    assert label is not None
    assert label.url == "/api/labels/lbl_fixed?customer_id=cust_becky"
    stored = next(iter(store.repo.returns.values()))
    assert stored["exception"] is True
    assert stored["destination"] == "store_credit"
    assert stored["reason"] == REASON
    assert stored["reasonKind"] == "other"
    assert stored["trackingNumber"] == "BKLY18440TEST"
    assert stored["carrier"] == CARRIER_NAME
    assert store.labels["lbl_fixed"]["address"] == "418 Linden Street, Oakland, CA 94607"
    assert get_label("cust_becky", "lbl_fixed") == {"_id": "lbl_fixed", "customerId": "cust_becky"}

    pdf = render_parcel_label(
        name=store.customer_name,
        address_lines=ADDRESS_LINES,
        carrier=stored["carrier"],
        tracking_number=stored["trackingNumber"],
        order_id="BLY-18440",
        title="Piranesi",
    )
    assert pdf.startswith(b"%PDF")
    assert stored["trackingNumber"].encode() in pdf
    assert b"418 Linden Street" in pdf
    assert b"Oakland" in pdf
    assert b"94607" in pdf
    assert b"Becky Alvarez" in pdf
    assert b"FedEx" not in pdf
    assert b"UPS" not in pdf

    again = machine.step(session, "yes", today=TODAY, now=NOW)
    assert store.calls.count("start_return") == 2
    assert len(store.repo.returns) == 1
    assert again.tools[0].payload["receiptId"] == done.tools[0].payload["receiptId"]
    assert again.tools[0].payload["trackingNumber"] == stored["trackingNumber"]


_ACCEPTS = (
    "yes",
    "yeah that'd be great",
    "yeah that would be great",
    "that works",
    "sounds good",
    "sure",
    "I'll take it",
    "I will take it",
)


def test_clear_yes_accepts_the_exception_and_a_no_does_not() -> None:
    for phrase in _ACCEPTS:
        assert GOLDEN[key(phrase)]["offer_reply"] == "accept", phrase
    for phrase in ("no", "never mind", "no thanks"):
        assert accepts_store_credit_exception(phrase) is False, phrase
        assert GOLDEN[key(phrase)]["offer_reply"] == "refuse", phrase
    assert accepts_store_credit_exception("the weather is nice today") is False
    assert "offer_reply" not in GOLDEN[key("the weather is nice today")]
    assert accepts_store_credit_exception("card is fine") is False
    assert GOLDEN[key("card is fine")]["offer_reply"] == "refuse"


def test_yeah_thatd_be_great_writes_one_store_credit_exception() -> None:
    store = _store()
    machine = Machine(store)
    session = _session()
    machine.step(session, "Is it too late to return Piranesi?", today=TODAY, now=NOW)
    offer = machine.step(session, REASON, today=TODAY, now=NOW)
    assert session.phase == "exception_offer"
    assert "15.99" in offer.template
    assert "start_return" not in store.calls

    for phrase in ("no thanks", "no", "never mind", "the weather is nice today", "card is fine"):
        held = machine.step(session, phrase, today=TODAY, now=NOW)
        assert session.phase == "exception_offer", phrase
        assert session.destination is None, phrase
        assert "start_return" not in store.calls, phrase
        assert "store credit" in held.template
        assert "Visa" not in held.template
        assert held.step == "Step: store credit exception"

    done = machine.step(session, "yeah that'd be great", today=TODAY, now=NOW)
    assert store.calls.count("start_return") == 1
    assert len(store.repo.returns) == 1
    assert done.step == "Step: receipt and label"
    assert done.tools[0].payload["destination"] == "store_credit"
    assert done.tools[0].payload["exception"] is True
    assert "Visa" not in done.template
    assert "15.99" in done.template
    assert "store credit" in done.template
    assert done.tools[0].payload["receiptId"] in done.template
    assert "parcel label" in done.template
    receipt = receipt_download(done, "cust_becky")
    label = label_download(done, "cust_becky")
    assert receipt is not None and receipt.receipt_id == "rcpt_fixed"
    assert label is not None
    stored = next(iter(store.repo.returns.values()))
    assert stored["destination"] == "store_credit"
    assert stored["exception"] is True

    again = machine.step(session, "yeah that'd be great", today=TODAY, now=NOW)
    assert store.calls.count("start_return") == 2
    assert len(store.repo.returns) == 1
    assert again.tools[0].payload["receiptId"] == done.tools[0].payload["receiptId"]
    assert again.tools[0].payload["destination"] == "store_credit"
    assert again.tools[0].payload["exception"] is True


def test_naming_the_old_book_first_skips_the_list() -> None:
    store = _store()
    session = _session()
    turn = Machine(store).step(
        session,
        "Is it too late to return Piranesi?",
        today=TODAY,
        now=NOW,
    )
    assert session.phase == "exception_why"
    assert turn.step == "Step: what happened"
    assert "Which book" not in turn.template
    assert "cannot go back on the Visa" in turn.template
    assert "start_return" not in store.calls


def test_in_window_title_stays_on_the_normal_return_and_card_is_fine_is_visa() -> None:
    store = _store()
    machine = Machine(store)
    session = _session()
    opened = machine.step(
        session,
        "Is it too late to return The Midnight Library?",
        today=TODAY,
        now=NOW,
    )
    assert session.phase == "ask_reason"
    assert session.exception is False
    assert session.order_id == "BLY-22018"
    assert "What made you want to send it back?" in opened.template
    assert "store credit exception" not in opened.template
    assert opened.step == "Step: why it's coming back"

    machine.step(session, "changed my mind", today=TODAY, now=NOW)
    assert session.phase == "choose_destination"
    done = machine.step(session, "card is fine", today=TODAY, now=NOW)
    assert done.tools[0].payload["destination"] == "original_payment"
    assert done.tools[0].payload.get("exception") is not True
    assert "Visa" in done.template
    assert done.step == "Step: receipt"
    assert label_download(done, "cust_becky") is None
    stored = next(iter(store.repo.returns.values()))
    assert stored.get("exception") is not True
    assert "trackingNumber" not in stored
    assert store.labels == {}


def test_a_book_still_packing_is_not_past_the_window() -> None:
    store = _store()
    session = _session()
    turn = Machine(store).step(
        session,
        "Is it too late to return Klara and the Sun?",
        today=TODAY,
        now=NOW,
    )
    assert "Klara and the Sun" in turn.template
    assert "has not been delivered" in turn.template
    assert "packing" in turn.template
    assert "past the" not in turn.template
    assert "past the window" not in turn.template
    assert session.phase == "which_book"
    assert session.exception is False
    assert session.order_id is None
    assert "start_return" not in store.calls
    assert unsupported_facts(turn.template, turn.payload) == []
    called_past = f"{turn.template} It is past the return window."
    assert accept_draft(called_past, turn.template, turn.payload, turn.required) == turn.template
    called_delivered = turn.template.replace("has not been delivered", "is delivered")
    assert accept_draft(called_delivered, turn.template, turn.payload, turn.required) == turn.template


def _progress(order_id: str, title: str, status: str) -> dict:
    return {
        "orderId": order_id,
        "title": title,
        "placedAt": datetime(2026, 10, 1, 14, tzinfo=timezone.utc),
        "status": status,
        "refundableCents": 1600,
        "paymentMethodId": "pm_becky_visa",
    }


def test_too_late_list_keeps_each_stored_trip_status() -> None:
    store = FakeStore(
        [
            _order("BLY-18440", "Piranesi", date(2026, 8, 10), date(2026, 8, 15), 1599, "fantasy"),
            _progress("BLY-44120", "Klara and the Sun", "packing"),
            _progress("BLY-44121", "The Night Circus", "shipped"),
            _progress("BLY-44122", "Educated", "on the way"),
            _progress("BLY-44123", "Beach Read", "out for delivery"),
        ]
    )
    turn = Machine(store).step(_session(), "Is it too late to return it?", today=TODAY, now=NOW)
    assert turn.step == "Step: which book"
    marks = {order["orderId"]: order["mark"] for order in turn.tools[0].payload["orders"]}
    assert marks["BLY-18440"] == "Delivered and past the 30-day window"
    assert marks["BLY-44120"] == "Still on the way, packing"
    assert marks["BLY-44121"] == "Still on the way, shipped"
    assert marks["BLY-44122"] == "Still on the way, on the way"
    assert marks["BLY-44123"] == "Still on the way, out for delivery"
    for order_id in ("BLY-44120", "BLY-44121", "BLY-44122", "BLY-44123"):
        assert order_id in turn.template
    assert "Delivered and past the 30-day window" in turn.template
    assert "Still on the way, packing" in turn.template
    assert "Still on the way, shipped" in turn.template
    assert "Still on the way, on the way" in turn.template
    assert "Still on the way, out for delivery" in turn.template
    assert unsupported_facts(turn.template, turn.payload) == []
    assert "start_return" not in store.calls


def test_i_will_take_it_stays_on_the_past_window_book() -> None:
    store = _store()
    machine = Machine(store)
    session = _session()
    opened = machine.step(session, "I want to return Piranesi", today=TODAY, now=NOW)
    assert session.phase == "exception_why"
    assert session.order_id == "BLY-18440"
    assert session.reason is None
    assert opened.step == "Step: what happened"
    assert "outside the 30-day return window" in opened.template
    assert "cannot go back on the card" in opened.template
    assert "What happened with it?" in opened.template
    assert "The Midnight Library" not in opened.template
    assert "Klara" not in opened.template
    assert "Visa" not in opened.template
    assert "store credit" not in opened.template.lower()
    assert unsupported_facts(opened.template, opened.payload) == []
    assert "start_return" not in store.calls

    for phrase in ("I will take it", "I'll take it", "yes"):
        fresh = _session()
        machine.step(fresh, "I want to return Piranesi", today=TODAY, now=NOW)
        held = machine.step(fresh, phrase, today=TODAY, now=NOW)
        assert fresh.phase == "exception_why"
        assert fresh.order_id == "BLY-18440"
        assert fresh.reason is None
        assert "What happened with it?" in held.template
        assert "The Midnight Library" not in held.template
        assert "Klara" not in held.template
        assert "Which one do you want to return?" not in held.template
        assert "store credit" not in held.template.lower()
        assert "Visa" not in held.template
        assert held.step == "Step: what happened"
        assert unsupported_facts(held.template, held.payload) == []

    assert "start_return" not in store.calls
    ready = _session()
    machine.step(ready, "return BLY-18440", today=TODAY, now=NOW)
    ready.reason = REASON
    ready.reason_kind = "other"
    offer = machine.step(ready, "I will take it", today=TODAY, now=NOW)
    assert ready.phase == "exception_offer"
    assert ready.order_id == "BLY-18440"
    assert ready.reason == REASON
    assert "store credit" in offer.template
    assert "Visa" not in offer.template
    assert "The Midnight Library" not in offer.template
    assert "Which one do you want to return?" not in offer.template
    assert "start_return" not in store.calls

    held_card = machine.step(ready, "card is fine", today=TODAY, now=NOW)
    assert ready.phase == "exception_offer"
    assert "start_return" not in store.calls
    assert "store credit" in held_card.template
    assert "Visa" not in held_card.template

    done = machine.step(ready, "I will take it", today=TODAY, now=NOW)
    assert store.calls.count("start_return") == 1
    assert done.tools[0].payload["destination"] == "store_credit"
    assert done.tools[0].payload["exception"] is True
    assert "Visa" not in done.template
    assert done.step == "Step: receipt and label"


def test_card_refund_of_an_ineligible_order_still_fails() -> None:
    store = _store()
    refused = store.start_return(
        "cust_becky",
        "BLY-18440",
        "original_payment",
        TODAY,
        NOW,
        exception=True,
    )
    assert refused["status"] == "not_completed"
    assert refused["reason"] == "ineligible"
    plain = store.start_return(
        "cust_becky",
        "BLY-18440",
        "store_credit",
        TODAY,
        NOW,
        exception=False,
    )
    assert plain["status"] == "not_completed"
    assert store.repo.returns == {}


def test_reset_removes_the_exception_return_receipt_and_label() -> None:
    database = _Database()
    database.orders.docs.append(
        {"_id": "BLY-18440", "status": "delivered", "lines": [{"title": "Piranesi"}]}
    )
    becky = next(doc for doc in database.customers.docs if doc["_id"] == "cust_becky")
    becky["shippingAddress"] = {
        "line1": "418 Linden Street",
        "city": "Oakland",
        "region": "CA",
        "postalCode": "94607",
    }
    database.returns.docs.append(
        {
            "_id": "ret_old_book",
            "customerId": "cust_becky",
            "orderId": "BLY-18440",
            "status": "completed",
            "reason": "pages fell out",
            "reasonKind": "other",
            "sentiment": "neutral",
            "receiptId": "rcpt_old_book",
            "createdAt": datetime(2026, 10, 4, 12, tzinfo=timezone.utc),
        }
    )
    database.receipts.docs.append(
        {
            "_id": "rcpt_old_book",
            "returnId": "ret_old_book",
            "orderId": "BLY-18440",
            "title": "Piranesi",
        }
    )
    database.labels = _Collection(
        [
            {
                "_id": "lbl_old_book",
                "customerId": "cust_becky",
                "returnId": "ret_old_book",
                "orderId": "BLY-18440",
            }
        ]
    )
    orders = _copy(database.orders)
    customers = _copy(database.customers)
    reset_bookly_demo(database)
    assert "ret_old_book" not in {doc["_id"] for doc in database.returns.docs}
    assert "rcpt_old_book" not in {doc["_id"] for doc in database.receipts.docs}
    assert database.labels.docs == []
    assert {doc["_id"] for doc in database.returns.docs} == {"ret_progress"}
    assert database.orders.docs == orders
    assert database.customers.docs == customers
    kept = next(doc for doc in database.memory.docs if doc["customerId"] == "cust_becky")
    assert kept["orderId"] == "BLY-18440"
    assert kept["title"] == "Piranesi"
    assert kept["reason"] == "pages fell out"


def _offered_piranesi() -> tuple[FakeStore, Machine, Session]:
    store = _store()
    machine = Machine(store)
    session = _session()
    machine.step(session, "Is it too late to return Piranesi?", today=TODAY, now=NOW)
    offer = machine.step(session, REASON, today=TODAY, now=NOW)
    assert session.phase == "exception_offer"
    assert session.order_id == "BLY-18440"
    assert "Is that acceptable?" in offer.template
    assert "start_return" not in store.calls
    return store, machine, session


def test_why_not_asks_to_confirm_then_yes_writes_once() -> None:
    for phrase in ("why not", "I guess", "whatever", "Why not?", "whatever!"):
        assert accepts_store_credit_exception(phrase) is False, phrase
        store, machine, session = _offered_piranesi()
        held = machine.step(session, phrase, today=TODAY, now=NOW)
        assert "start_return" not in store.calls, phrase
        assert session.phase == "exception_offer", phrase
        assert session.order_id == "BLY-18440", phrase
        assert session.destination is None, phrase
        assert "confirm" in held.template.lower(), phrase
        assert "store credit" in held.template, phrase
        assert "15.99" in held.template, phrase
        assert "BLY-18440" in held.template, phrase
        assert "Piranesi" in held.template, phrase
        assert "Is that acceptable?" not in held.template, phrase
        assert "Visa" not in held.template, phrase
        assert held.choices == [], phrase
        assert unsupported_facts(held.template, held.payload) == [], phrase
        assert held.tools[0].payload["amount"] == "15.99"
        assert held.tools[0].payload["orderId"] == "BLY-18440"

    store, machine, session = _offered_piranesi()
    machine.step(session, "why not", today=TODAY, now=NOW)
    refused = machine.step(session, "no", today=TODAY, now=NOW)
    assert "start_return" not in store.calls
    assert session.destination is None
    assert session.order_id == "BLY-18440"
    assert "Visa" not in refused.template
    card = machine.step(session, "card is fine", today=TODAY, now=NOW)
    assert "start_return" not in store.calls
    assert session.destination is None
    assert session.order_id == "BLY-18440"
    assert "Visa" not in card.template
    assert "store credit" in card.template

    done = machine.step(session, "yes", today=TODAY, now=NOW)
    assert store.calls.count("start_return") == 1
    assert len(store.repo.returns) == 1
    assert done.tools[0].payload["destination"] == "store_credit"
    assert done.tools[0].payload["exception"] is True
    assert done.tools[0].payload["orderId"] == "BLY-18440"
    assert "15.99" in done.template
    assert "Visa" not in done.template


def _progress_order(order_id: str, title: str, status: str, hour: int) -> dict:
    return {
        "orderId": order_id,
        "title": title,
        "placedAt": datetime(2026, 10, 1, hour, tzinfo=timezone.utc),
        "status": status,
        "refundableCents": 1700,
        "paymentMethodId": "pm_becky_visa",
    }


def _becky_orders() -> list[dict]:
    """Becky's recent orders, newest first, including the returned Piranesi."""

    return [
        _progress_order("BLY-44121", "The Night Circus", "shipped", 16),
        _progress_order("BLY-44120", "Klara and the Sun", "packing", 14),
        _order("BLY-22044", "Mexican Gothic", date(2026, 9, 30), date(2026, 10, 1), 1699, "horror"),
        _order("BLY-22018", "The Midnight Library", date(2026, 9, 24), date(2026, 9, 26), 1699),
        _order("BLY-22002", "Circe", date(2026, 9, 11), date(2026, 9, 15), 1700),
        _order("BLY-18440", "Piranesi", date(2026, 8, 10), date(2026, 8, 15), 1599, "fantasy"),
    ]


def _finish_piranesi(store: FakeStore) -> tuple[Machine, Session]:
    machine = Machine(store)
    session = _session()
    machine.step(session, "I want to return Piranesi", today=TODAY, now=NOW)
    machine.step(session, REASON, today=TODAY, now=NOW)
    done = machine.step(session, "yes", today=TODAY, now=NOW)
    assert session.phase == "done"
    assert done.tools[0].payload["status"] == "completed"
    assert len(store.repo.returns) == 1
    return machine, session


def test_done_phase_return_lists_books_without_a_completed_return() -> None:
    """After Piranesi is stored, another return asks which book and hides that order."""

    store = FakeStore(_becky_orders())
    machine, session = _finish_piranesi(store)
    stored = next(iter(store.repo.returns.values()))
    assert stored["orderId"] == "BLY-18440"
    assert stored["status"] == "completed"
    writes = store.calls.count("start_return")

    status = machine.step(session, "where is my order", today=TODAY, now=NOW)
    assert status.intent == "order_status"
    assert status.step == "Step: order status"
    assert "anything else" not in status.template.lower()
    assert session.phase == "done"
    assert "start_return" not in status.tools[0].name

    named = machine.step(session, "what's the status of BLY-18440", today=TODAY, now=NOW)
    assert named.intent == "order_status"
    assert named.step == "Step: order status"
    assert "Piranesi" in named.template
    assert "delivered" in named.template
    assert session.phase == "done"
    assert named.choices == []

    hedge = machine.step(session, "why not", today=TODAY, now=NOW)
    assert hedge.template == "Sure. Is there anything else I can help with?"
    assert hedge.step == "Step: anything else"
    assert hedge.choices == []
    assert session.phase == "done"
    assert store.calls.count("start_return") == writes

    phrases = ("return another book", "return", "I want to return a book")
    expected_ids = ["BLY-44121", "BLY-44120", "BLY-22044", "BLY-22018", "BLY-22002"]
    expected_marks = [
        "Still on the way, shipped",
        "Still on the way, packing",
        "Delivered and inside the 30-day window",
        "Delivered and inside the 30-day window",
        "Delivered and inside the 30-day window",
    ]
    for phrase in phrases:
        fresh = FakeStore(_becky_orders())
        again_machine, again_session = _finish_piranesi(fresh)
        turn = again_machine.step(again_session, phrase, today=TODAY, now=NOW)
        assert turn.template == "Which book do you want to return?", phrase
        assert "anything else" not in turn.template.lower(), phrase
        assert turn.step == "Step: which order", phrase
        assert [choice.order_id for choice in turn.choices] == expected_ids, phrase
        assert [choice.mark for choice in turn.choices] == expected_marks, phrase
        assert "BLY-18440" not in turn.template, phrase
        assert "Piranesi" not in turn.template, phrase
        payload_ids = [order["orderId"] for order in turn.tools[0].payload["orders"]]
        assert payload_ids == expected_ids, phrase
        assert again_session.phase == "identify_order", phrase
        assert again_session.exception is False, phrase
        assert len(fresh.repo.returns) == 1, phrase
        assert next(iter(fresh.repo.returns.values()))["status"] == "completed"
        assert fresh.calls.count("start_return") == 1, phrase

    clicked = machine.step(session, "return another book", today=TODAY, now=NOW)
    assert [choice.order_id for choice in clicked.choices] == expected_ids
    picked = machine.step(session, "BLY-22018", today=TODAY, now=NOW)
    assert session.order_id == "BLY-22018"
    assert picked.choices == []
    assert "What made you want to send it back?" in picked.template
    assert store.calls.count("start_return") == writes

    typed_store = FakeStore(_becky_orders())
    typed_machine, typed_session = _finish_piranesi(typed_store)
    typed_machine.step(typed_session, "return another book", today=TODAY, now=NOW)
    typed = typed_machine.step(typed_session, "Circe", today=TODAY, now=NOW)
    assert typed_session.order_id == "BLY-22002"
    assert typed.choices == []
    assert "Circe" in typed.template
    assert "What made you want to send it back?" in typed.template

    list_session = Session(id="conv_list", customer_id="cust_becky")
    listed = typed_machine.step(list_session, "I want to return a product", today=TODAY, now=NOW)
    assert "BLY-18440" not in [choice.order_id for choice in listed.choices]
    stayed = typed_machine.step(list_session, "Piranesi", today=TODAY, now=NOW)
    assert list_session.order_id is None
    assert stayed.template == "Which book do you want to return?"
    assert "BLY-18440" not in [choice.order_id for choice in stayed.choices]

    goodbye = Session(
        id="conv_bye",
        customer_id="cust_becky",
        phase="done",
        exception=True,
        order_id="BLY-18440",
        title="Piranesi",
    )
    closed = machine.step(goodbye, "no thanks", today=TODAY, now=NOW)
    assert goodbye.phase == "closed"
    assert closed.step == "Step: close"
    assert closed.choices == []
    assert len(store.repo.returns) == 1
    assert next(iter(store.repo.returns.values()))["orderId"] == "BLY-18440"
