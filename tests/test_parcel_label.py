"""A parcel label after a completed return. No Claude and no Atlas."""

from datetime import date

from bookly_support.agent.label_pdf import CARRIER_NAME, render_parcel_label
from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.return_agent import label_download

from test_allowlist import NOW, TODAY, FakeStore, _order

_PHRASES = (
    "shipping label?",
    "shipping label",
    "send the label",
    "where's my label",
)
ADDRESS_LINES = ["418 Linden Street", "Oakland, CA 94607"]


def _visa_done() -> tuple[FakeStore, Machine, Session]:
    store = FakeStore(
        [_order("BLY-22018", "The Midnight Library", date(2026, 9, 24), date(2026, 9, 26), 1699)]
    )
    machine = Machine(store)
    session = Session(id="conv_label", customer_id="cust_becky")
    machine.step(session, "I want to return The Midnight Library", today=TODAY, now=NOW)
    machine.step(session, "changed my mind", today=TODAY, now=NOW)
    done = machine.step(session, "the original payment method", today=TODAY, now=NOW)
    assert session.phase == "done"
    assert done.tools[0].payload["destination"] == "original_payment"
    assert done.tools[0].payload.get("labelId") is None
    stored = next(iter(store.repo.returns.values()))
    assert "trackingNumber" not in stored
    assert store.labels == {}
    return store, machine, session


def test_shipping_label_after_a_card_return_is_not_a_topic_list() -> None:
    store, machine, session = _visa_done()
    first = None
    label_id = None
    for phrase in _PHRASES:
        turn = machine.step(session, phrase, today=TODAY, now=NOW)
        assert turn.step == "Step: parcel label", phrase
        assert "which topic" not in turn.template.lower(), phrase
        assert turn.choices == []
        assert [tool.name for tool in turn.tools] == ["issue_parcel_label"]
        assert all(tool.name != "get_policy_article" for tool in turn.tools)
        payload = turn.tools[0].payload
        tracking = payload["trackingNumber"]
        assert tracking
        assert tracking in turn.template
        assert payload["carrier"] == CARRIER_NAME
        assert CARRIER_NAME in turn.template
        download = label_download(turn, "cust_becky")
        assert download is not None
        assert download.label_id == payload["labelId"]
        assert download.url == f"/api/labels/{payload['labelId']}?customer_id=cust_becky"
        if first is None:
            first = tracking
            label_id = payload["labelId"]
        else:
            assert tracking == first
            assert payload["labelId"] == label_id
    stored = next(iter(store.repo.returns.values()))
    assert stored["trackingNumber"] == first
    assert stored["carrier"] == CARRIER_NAME
    assert stored["labelId"] == label_id
    assert len(store.labels) == 1
    assert store.labels[label_id]["address"] == "418 Linden Street, Oakland, CA 94607"
    pdf = render_parcel_label(
        name=store.customer_name,
        address_lines=ADDRESS_LINES,
        carrier=stored["carrier"],
        tracking_number=stored["trackingNumber"],
        order_id="BLY-22018",
        title="The Midnight Library",
    )
    assert pdf.startswith(b"%PDF")
    assert stored["trackingNumber"].encode() in pdf
    assert b"418 Linden Street" in pdf
    assert b"FedEx" not in pdf
    assert b"UPS" not in pdf


def test_store_credit_label_is_reused_and_survives_another_return() -> None:
    from test_window_exception import _finish_piranesi, _store

    store = _store()
    machine, session = _finish_piranesi(store)
    stored = next(iter(store.repo.returns.values()))
    turn = machine.step(session, "shipping label?", today=TODAY, now=NOW)
    assert "which topic" not in turn.template.lower()
    assert turn.tools[0].payload["trackingNumber"] == stored["trackingNumber"] == "BKLY18440TEST"
    assert turn.tools[0].payload["labelId"] == "lbl_fixed"
    assert label_download(turn, "cust_becky") is not None

    listed = machine.step(session, "return another book", today=TODAY, now=NOW)
    assert session.phase == "identify_order"
    assert session.return_id == stored["_id"]
    assert "which topic" not in listed.template.lower()
    again = machine.step(session, "send the label", today=TODAY, now=NOW)
    assert again.tools[0].payload["trackingNumber"] == "BKLY18440TEST"
    assert again.tools[0].payload["labelId"] == "lbl_fixed"
    assert len(store.repo.returns) == 1
    assert len(store.labels) == 1


def test_shipping_label_without_a_return_does_not_create_one() -> None:
    store = FakeStore(
        [_order("BLY-22018", "The Midnight Library", date(2026, 9, 24), date(2026, 9, 26), 1699)]
    )
    machine = Machine(store)
    for phrase in _PHRASES:
        session = Session(id="conv_none", customer_id="cust_becky")
        turn = machine.step(session, phrase, today=TODAY, now=NOW)
        assert turn.step == "Step: parcel label", phrase
        assert turn.template == "There isn't a parcel label yet, because no return is done."
        assert "which topic" not in turn.template.lower()
        assert turn.tools == []
        assert turn.choices == []
        assert label_download(turn, "cust_becky") is None
        assert session.phase == "identify_order"
    assert store.labels == {}
    assert store.repo.returns == {}
    assert "issue_parcel_label" not in store.calls
    assert "start_return" not in store.calls
    assert "get_policy_article" not in store.calls

    policy = machine.step(
        Session(id="conv_ship", customer_id="cust_becky"),
        "How long does shipping take?",
        today=TODAY,
        now=NOW,
    )
    assert policy.tools[0].payload["id"] == "shipping-speed"
    assert store.labels == {}


def test_done_phase_without_a_stored_return_does_not_invent_a_label() -> None:
    store = FakeStore(
        [_order("BLY-22044", "Mexican Gothic", date(2026, 9, 30), date(2026, 10, 1), 1699, "horror")]
    )
    session = Session(
        id="conv_done",
        customer_id="cust_becky",
        phase="done",
        order_id="BLY-22044",
        title="Mexican Gothic",
    )
    turn = Machine(store).step(session, "shipping label?", today=TODAY, now=NOW)
    assert turn.template == "There isn't a parcel label yet, because no return is done."
    assert "which topic" not in turn.template.lower()
    assert store.labels == {}
    assert store.repo.returns == {}
