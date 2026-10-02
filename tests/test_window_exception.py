"""Too late, then a store-credit exception. No Claude and no Atlas."""

from datetime import date, datetime, timezone

from bookly_support.agent.checker import accept_draft, unsupported_facts
from bookly_support.agent.label_pdf import CARRIER_NAME, render_parcel_label
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


def test_too_late_lists_delivered_books_and_does_not_start_a_return() -> None:
    store = _store()
    turn = Machine(store).step(_session(), "Is it too late to return a book?", today=TODAY, now=NOW)
    assert [tool.name for tool in turn.tools] == ["list_recent_orders"]
    assert "start_return" not in store.calls
    assert "get_order" not in store.calls
    assert turn.step == "Step: which book"
    assert "Piranesi" in turn.template
    assert "The Midnight Library" in turn.template
    assert "Klara" not in turn.template
    assert "past the 30 days" in turn.template
    assert "inside the 30 days" in turn.template
    assert "August 15, 2026" in turn.template
    assert "September 26, 2026" in turn.template
    assert unsupported_facts(turn.template, turn.payload) == []
    windows = {order["title"]: order["window"] for order in turn.tools[0].payload["orders"]}
    assert windows == {"Piranesi": "past", "The Midnight Library": "inside"}


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
    assert "packing" in turn.template
    assert "isn't past the return window" in turn.template
    assert session.phase == "which_book"
    assert session.exception is False
    assert "start_return" not in store.calls
    assert unsupported_facts(turn.template, turn.payload) == []


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
