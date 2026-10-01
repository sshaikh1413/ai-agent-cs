from datetime import date, datetime, timezone
from pathlib import Path

from bookly_support.agent.allowlist import TOOL_NAMES, ToolNotAllowed, allowed_tools, run_tool
from bookly_support.agent.eligibility import is_eligible
from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.queries import (
    completed_return,
    get_order,
    get_payment_method,
    get_receipt,
    list_recent_orders,
)
from bookly_support.agent.returns import commit_return

TODAY = date(2026, 10, 1)
NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def test_only_the_four_return_tools_exist() -> None:
    assert TOOL_NAMES == (
        "list_recent_orders",
        "get_order",
        "get_refund_options",
        "start_return",
    )
    assert allowed_tools("identify_order") == frozenset({"list_recent_orders", "get_order"})
    assert "start_return" not in allowed_tools("identify_order")
    assert "get_refund_options" not in allowed_tools("identify_order")
    assert allowed_tools("choose_destination") == frozenset({"get_refund_options"})
    assert allowed_tools("write") == frozenset({"start_return"})
    assert allowed_tools("done") == frozenset()
    assert allowed_tools("closed") == frozenset()


def test_gate_does_not_run_a_disallowed_tool() -> None:
    called = False

    def write() -> None:
        nonlocal called
        called = True

    try:
        run_tool("choose_destination", "start_return", write)
    except ToolNotAllowed:
        pass
    else:
        raise AssertionError("start_return ran before the destination phase")
    assert called is False


def test_queries_include_customer_id() -> None:
    assert list_recent_orders("cust_becky") == {"customerId": "cust_becky"}
    assert get_order("cust_becky", "BLY-22018")["customerId"] == "cust_becky"
    assert get_payment_method("cust_becky", "pm_becky_visa")["customerId"] == "cust_becky"
    assert completed_return("cust_becky", "BLY-22018")["customerId"] == "cust_becky"
    assert get_receipt("cust_becky", "rcpt_abc")["customerId"] == "cust_becky"


def test_source_has_no_vector_search_or_password_reset() -> None:
    text = "\n".join(path.read_text() for path in (ROOT / "src").rglob("*.py"))
    assert "$vectorSearch" not in text
    assert "vector_search" not in text.lower()
    assert "send_password_reset" not in text


def _order(order_id: str, title: str, placed: date, delivered: date, cents: int) -> dict:
    return {
        "orderId": order_id,
        "title": title,
        "placedAt": datetime(placed.year, placed.month, placed.day, 6, tzinfo=timezone.utc),
        "deliveredAt": datetime(delivered.year, delivered.month, delivered.day, 6, tzinfo=timezone.utc),
        "status": "delivered",
        "refundableCents": cents,
        "paymentMethodId": "pm_becky_visa",
    }


class _Repo:
    def __init__(self) -> None:
        self.returns: dict[str, dict] = {}
        self.receipts: dict[str, dict] = {}

    def find_completed_return(self, customer_id: str, order_id: str) -> dict | None:
        for document in self.returns.values():
            if document["customerId"] == customer_id and document["orderId"] == order_id:
                return document
        return None

    def find_receipt(self, customer_id: str, receipt_id: str) -> dict | None:
        document = self.receipts.get(receipt_id)
        if document is None or document["customerId"] != customer_id:
            return None
        return document

    def insert_return_and_receipt(self, return_doc: dict, receipt_doc: dict) -> None:
        self.returns[return_doc["_id"]] = return_doc
        self.receipts[receipt_doc["_id"]] = receipt_doc


class FakeStore:
    def __init__(self, orders: list[dict]) -> None:
        self.orders = orders
        self.repo = _Repo()
        self.calls: list[str] = []

    def list_recent_orders(self, customer_id: str) -> list[dict]:
        assert customer_id == "cust_becky"
        self.calls.append("list_recent_orders")
        return list(self.orders)

    def get_order(self, customer_id: str, order_id: str, today: date) -> dict | None:
        assert customer_id == "cust_becky"
        self.calls.append("get_order")
        order = next((item for item in self.orders if item["orderId"] == order_id), None)
        if order is None:
            return None
        detail = dict(order)
        detail["eligible"] = is_eligible(detail["deliveredAt"], today, 30)
        detail["returnWindowDays"] = 30
        detail["policy"] = "Delivered books can be returned within 30 days."
        return detail

    def get_refund_options(self, customer_id: str, order_id: str) -> dict | None:
        assert customer_id == "cust_becky"
        self.calls.append("get_refund_options")
        order = next(item for item in self.orders if item["orderId"] == order_id)
        cents = int(order["refundableCents"])
        amount = f"{cents // 100}.{cents % 100:02d}"
        return {
            "orderId": order_id,
            "title": order["title"],
            "refundableCents": cents,
            "amount": amount,
            "originalPayment": {"available": True, "brand": "Visa", "last4": "4242"},
            "storeCredit": {"available": True, "refundableCents": cents, "amount": amount},
        }

    def start_return(self, customer_id: str, order_id: str, destination: str, today: date, now: datetime) -> dict:
        assert customer_id == "cust_becky"
        self.calls.append("start_return")
        order = next(item for item in self.orders if item["orderId"] == order_id)
        return commit_return(
            self.repo,
            customer_id=customer_id,
            order_id=order_id,
            destination=destination,
            title=order["title"],
            amount_cents=int(order["refundableCents"]),
            brand="Visa",
            last4="4242",
            now=now,
            new_ids=lambda: ("ret_fixed", "rcpt_fixed"),
        )


def _becky_store() -> FakeStore:
    return FakeStore(
        [
            _order("BLY-22018", "The Midnight Library", date(2026, 9, 24), date(2026, 9, 26), 1699),
            _order("BLY-22002", "Circe", date(2026, 9, 11), date(2026, 9, 15), 1700),
        ]
    )


def test_script_does_not_write_until_she_chooses_the_card() -> None:
    store = _becky_store()
    machine = Machine(store)
    session = Session(id="conv_test", customer_id="cust_becky")

    first = machine.step(session, "I want to return a product", today=TODAY, now=NOW)
    assert [tool.name for tool in first.tools] == ["list_recent_orders"]
    assert "The Midnight Library" in first.template
    assert "Circe" in first.template
    assert "start_return" not in store.calls

    second = machine.step(session, "the one from about a week ago", today=TODAY, now=NOW)
    assert [tool.name for tool in second.tools] == [
        "list_recent_orders",
        "get_order",
        "get_refund_options",
    ]
    assert session.phase == "choose_destination"
    assert session.order_id == "BLY-22018"
    assert "4242" in second.template
    assert "16.99" in second.template
    assert "The Midnight Library" in second.template
    assert "rcpt_" not in second.template
    assert store.calls.count("start_return") == 0

    talk = machine.step(session, "I'll start the return", today=TODAY, now=NOW)
    assert [tool.name for tool in talk.tools] == ["get_refund_options"]
    assert store.calls.count("start_return") == 0
    assert session.phase == "choose_destination"

    third = machine.step(session, "the original payment method", today=TODAY, now=NOW)
    assert [tool.name for tool in third.tools] == ["start_return"]
    assert third.tools[0].payload["status"] == "completed"
    assert "rcpt_fixed" in third.template
    assert "4242" in third.template
    assert "16.99" in third.template
    assert session.phase == "done"

    fourth = machine.step(session, "no", today=TODAY, now=NOW)
    assert fourth.tools == []
    assert session.phase == "closed"
    assert store.calls.count("start_return") == 1


def test_two_orders_in_the_same_week_ask_instead_of_choosing() -> None:
    store = FakeStore(
        [
            _order("BLY-22018", "The Midnight Library", date(2026, 9, 24), date(2026, 9, 26), 1699),
            _order("BLY-22019", "Piranesi", date(2026, 9, 25), date(2026, 9, 26), 1600),
        ]
    )
    session = Session(id="conv_test", customer_id="cust_becky")
    turn = Machine(store).step(session, "the one from about a week ago", today=TODAY, now=NOW)
    assert "get_refund_options" not in [tool.name for tool in turn.tools]
    assert "start_return" not in store.calls
    assert session.order_id is None
    assert "Which one" in turn.template


def test_closed_window_does_not_offer_a_refund() -> None:
    store = FakeStore(
        [_order("BLY-11004", "Old Book", date(2026, 8, 1), date(2026, 8, 2), 1000)]
    )
    session = Session(id="conv_test", customer_id="cust_becky")
    turn = Machine(store).step(session, "I want to return BLY-11004", today=TODAY, now=NOW)
    assert "get_refund_options" not in [tool.name for tool in turn.tools]
    assert "start_return" not in store.calls
    assert "30-day" in turn.template
    assert session.phase == "identify_order"
