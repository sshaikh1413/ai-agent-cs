from datetime import date, datetime, timezone
from pathlib import Path

from bookly_support.agent.allowlist import TOOL_NAMES, ToolNotAllowed, allowed_tools, run_tool
from bookly_support.agent.discounts import DuplicateDiscount, issue_goodwill_discount
from bookly_support.agent.eligibility import is_eligible
from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.queries import (
    completed_return,
    completed_return_by_id,
    get_order,
    get_payment_method,
    get_receipt,
    goodwill_discount,
    list_recent_orders,
)
from bookly_support.agent.recommendations import choose_recommendation
from bookly_support.agent.return_agent import receipt_download
from bookly_support.agent.returns import commit_return

TODAY = date(2026, 10, 1)
NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def test_only_the_return_tools_exist() -> None:
    assert TOOL_NAMES == (
        "list_recent_orders",
        "get_order",
        "get_refund_options",
        "start_return",
        "recommend_book",
        "issue_goodwill_discount",
    )
    assert allowed_tools("identify_order") == frozenset({"list_recent_orders", "get_order"})
    assert "start_return" not in allowed_tools("identify_order")
    assert "get_refund_options" not in allowed_tools("identify_order")
    assert "recommend_book" not in allowed_tools("identify_order")
    assert allowed_tools("ask_reason") == frozenset()
    assert allowed_tools("empathy") == frozenset({"recommend_book"})
    assert allowed_tools("empathy", "other") == frozenset({"recommend_book"})
    assert allowed_tools("empathy", "late_delivery") == frozenset(
        {"recommend_book", "issue_goodwill_discount"}
    )
    assert "issue_goodwill_discount" not in allowed_tools("write", "late_delivery")
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


def test_discount_is_blocked_unless_the_reason_is_late() -> None:
    called = False

    def write() -> None:
        nonlocal called
        called = True

    try:
        run_tool("empathy", "issue_goodwill_discount", write, reason_kind="other")
    except ToolNotAllowed:
        pass
    else:
        raise AssertionError("discount ran for a reason that is not late delivery")
    assert called is False

    try:
        run_tool("identify_order", "recommend_book", write)
    except ToolNotAllowed:
        pass
    else:
        raise AssertionError("recommend_book ran outside the empathy phase")
    assert called is False


def test_queries_include_customer_id() -> None:
    assert list_recent_orders("cust_becky") == {"customerId": "cust_becky"}
    assert get_order("cust_becky", "BLY-22018")["customerId"] == "cust_becky"
    assert get_payment_method("cust_becky", "pm_becky_visa")["customerId"] == "cust_becky"
    assert completed_return("cust_becky", "BLY-22018")["customerId"] == "cust_becky"
    assert completed_return_by_id("cust_becky", "ret_one") == {
        "_id": "ret_one",
        "customerId": "cust_becky",
        "status": "completed",
    }
    assert get_receipt("cust_becky", "rcpt_abc")["customerId"] == "cust_becky"
    assert goodwill_discount("cust_bob", "BLY-33010") == {
        "customerId": "cust_bob",
        "orderId": "BLY-33010",
    }


def test_source_has_no_vector_search_or_password_reset() -> None:
    text = "\n".join(path.read_text() for path in (ROOT / "src").rglob("*.py"))
    assert "$vectorSearch" not in text
    assert "vector_search" not in text.lower()
    assert "send_password_reset" not in text


def _order(
    order_id: str,
    title: str,
    placed: date,
    delivered: date,
    cents: int,
    genre: str | None = None,
) -> dict:
    order = {
        "orderId": order_id,
        "title": title,
        "placedAt": datetime(placed.year, placed.month, placed.day, 6, tzinfo=timezone.utc),
        "deliveredAt": datetime(delivered.year, delivered.month, delivered.day, 6, tzinfo=timezone.utc),
        "status": "delivered",
        "refundableCents": cents,
        "paymentMethodId": "pm_becky_visa",
    }
    if genre:
        order["genre"] = genre
    return order


class _Discounts:
    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def find_discount(self, customer_id: str, order_id: str) -> dict | None:
        for document in self.docs.values():
            if document["customerId"] == customer_id and document["orderId"] == order_id:
                return document
        return None

    def insert_discount(self, document: dict) -> None:
        if self.find_discount(document["customerId"], document["orderId"]):
            raise DuplicateDiscount
        self.docs[document["_id"]] = dict(document)


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
    def __init__(
        self,
        orders: list[dict],
        customer_id: str = "cust_becky",
        catalog: list[dict] | None = None,
    ) -> None:
        self.orders = orders
        self.customer_id = customer_id
        self.catalog = catalog or []
        self.repo = _Repo()
        self.discounts = _Discounts()
        self.calls: list[str] = []
        self._discount_codes_used: list[str] = []

    def list_recent_orders(self, customer_id: str) -> list[dict]:
        assert customer_id == self.customer_id
        self.calls.append("list_recent_orders")
        return list(self.orders)

    def get_order(self, customer_id: str, order_id: str, today: date) -> dict | None:
        assert customer_id == self.customer_id
        self.calls.append("get_order")
        order = next((item for item in self.orders if item["orderId"] == order_id), None)
        if order is None:
            return None
        detail = dict(order)
        detail["eligible"] = is_eligible(detail["deliveredAt"], today, 30)
        detail["returnWindowDays"] = 30
        detail["policy"] = "Delivered books can be returned within 30 days."
        return detail

    def recommend_book(self, customer_id: str) -> dict:
        assert customer_id == self.customer_id
        self.calls.append("recommend_book")
        chosen = choose_recommendation(
            [order["title"] for order in self.orders],
            self.catalog,
        )
        if chosen is None:
            return {"title": None, "genre": None, "author": None}
        return chosen

    def issue_goodwill_discount(self, customer_id: str, order_id: str, now: datetime) -> dict:
        assert customer_id == self.customer_id
        self.calls.append("issue_goodwill_discount")

        def new_code() -> str:
            code = "BLY20-ABC12345"
            self._discount_codes_used.append(code)
            return code

        return issue_goodwill_discount(
            self.discounts,
            customer_id=customer_id,
            order_id=order_id,
            now=now,
            new_code=new_code,
        )

    def get_refund_options(self, customer_id: str, order_id: str) -> dict | None:
        assert customer_id == self.customer_id
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

    def start_return(
        self,
        customer_id: str,
        order_id: str,
        destination: str,
        today: date,
        now: datetime,
        reason: str | None = None,
        reason_kind: str | None = None,
    ) -> dict:
        assert customer_id == self.customer_id
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
            reason=reason,
            reason_kind=reason_kind,
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
    assert [tool.name for tool in second.tools] == ["list_recent_orders", "get_order"]
    assert session.phase == "ask_reason"
    assert session.order_id == "BLY-22018"
    assert "What made you want to send it back?" in second.template
    assert "4242" not in second.template
    assert "rcpt_" not in second.template
    assert store.calls.count("start_return") == 0
    assert "recommend_book" not in store.calls
    assert "issue_goodwill_discount" not in store.calls

    reason = machine.step(session, "changed my mind", today=TODAY, now=NOW)
    assert [tool.name for tool in reason.tools] == ["get_refund_options"]
    assert session.phase == "choose_destination"
    assert session.reason_kind == "other"
    assert "4242" in reason.template
    assert "16.99" in reason.template
    assert "The Midnight Library" in reason.template
    assert "recommend_book" not in store.calls
    assert "issue_goodwill_discount" not in store.calls

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
    stored = next(iter(store.repo.returns.values()))
    assert stored["reason"] == "changed my mind"
    assert stored["reasonKind"] == "other"

    fourth = machine.step(session, "no", today=TODAY, now=NOW)
    assert fourth.tools == []
    assert session.phase == "closed"
    assert store.calls.count("start_return") == 1


def test_reason_is_stored_on_the_return_only_after_it_completes() -> None:
    store = _becky_store()
    machine = Machine(store)
    session = Session(id="conv_reason", customer_id="cust_becky")
    machine.step(session, "I want to return The Midnight Library", today=TODAY, now=NOW)
    asked = machine.step(session, "It arrived late", today=TODAY, now=NOW)
    assert session.reason == "It arrived late"
    assert session.reason_kind == "late_delivery"
    assert store.repo.returns == {}
    assert receipt_download(asked, "cust_becky") is None
    assert all("reason" not in order and "reasonKind" not in order for order in store.orders)

    done = machine.step(session, "store credit", today=TODAY, now=NOW)
    assert [tool.name for tool in done.tools] == ["start_return"]
    stored = next(iter(store.repo.returns.values()))
    assert stored["status"] == "completed"
    assert stored["reason"] == "It arrived late"
    assert stored["reasonKind"] == "late_delivery"
    assert stored["orderId"] == "BLY-22018"
    link = receipt_download(done, "cust_becky")
    assert link is not None
    assert link.receipt_id == stored["receiptId"] == "rcpt_fixed"
    assert link.url == "/api/receipts/rcpt_fixed?customer_id=cust_becky"
    assert "ready to download" in done.template
    assert all("reason" not in order and "reasonKind" not in order for order in store.orders)


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


_CATALOG = [
    {"title": "The Haunting of Hill House", "genre": "horror", "author": "Shirley Jackson"},
    {"title": "Mexican Gothic", "genre": "horror", "author": "Silvia Moreno-Garcia"},
    {"title": "Piranesi", "genre": "fantasy", "author": "Susanna Clarke"},
    {"title": "Project Hail Mary", "genre": "science fiction", "author": "Andy Weir"},
]


def test_horror_path_recommends_a_book_and_skips_the_discount() -> None:
    store = FakeStore(
        [_order("BLY-22044", "Mexican Gothic", date(2026, 9, 30), date(2026, 10, 1), 1699, "horror")],
        catalog=_CATALOG,
    )
    session = Session(id="conv_horror", customer_id="cust_becky")
    machine = Machine(store)
    machine.step(session, "I want to return Mexican Gothic", today=TODAY, now=NOW)
    assert session.phase == "ask_reason"
    turn = machine.step(session, "It wasn't scary at all", today=TODAY, now=NOW)
    assert [tool.name for tool in turn.tools] == ["recommend_book", "get_refund_options"]
    assert "issue_goodwill_discount" not in store.calls
    assert turn.tools[0].payload["title"] == "Piranesi"
    assert "not scary" in turn.template
    assert "Piranesi" in turn.template
    assert "20%" not in turn.template
    assert session.phase == "choose_destination"
    assert session.reason_kind == "other"


def test_late_delivery_issues_one_code_and_a_second_call_matches() -> None:
    store = FakeStore(
        [_order("BLY-33010", "A Gentleman in Moscow", date(2026, 9, 12), date(2026, 9, 28), 1800, "fiction")],
        customer_id="cust_bob",
        catalog=_CATALOG,
    )
    session = Session(id="conv_bob", customer_id="cust_bob")
    machine = Machine(store)
    machine.step(session, "I want to return A Gentleman in Moscow", today=TODAY, now=NOW)
    turn = machine.step(
        session,
        "It was a birthday gift and it arrived late",
        today=TODAY,
        now=NOW,
    )
    assert [tool.name for tool in turn.tools] == ["issue_goodwill_discount", "get_refund_options"]
    assert "recommend_book" not in store.calls
    assert store.calls.count("issue_goodwill_discount") == 1
    assert store._discount_codes_used == ["BLY20-ABC12345"]
    code = turn.tools[0].payload["code"]
    assert code == "BLY20-ABC12345"
    assert "20%" in turn.template
    assert code in turn.template
    assert "Piranesi" not in turn.template
    assert "missed" in turn.template
    assert session.reason_kind == "late_delivery"

    again = store.issue_goodwill_discount("cust_bob", "BLY-33010", NOW)
    assert again["code"] == code
    assert again["percent"] == 20
    assert store._discount_codes_used == ["BLY20-ABC12345"]
    assert len(store.discounts.docs) == 1


def test_late_horror_gets_the_discount_and_not_a_recommendation() -> None:
    store = FakeStore(
        [_order("BLY-22044", "Mexican Gothic", date(2026, 9, 30), date(2026, 10, 1), 1699, "horror")],
        catalog=_CATALOG,
    )
    session = Session(id="conv_late_horror", customer_id="cust_becky")
    machine = Machine(store)
    machine.step(session, "I want to return Mexican Gothic", today=TODAY, now=NOW)
    turn = machine.step(session, "the delivery was late", today=TODAY, now=NOW)
    assert [tool.name for tool in turn.tools] == ["issue_goodwill_discount", "get_refund_options"]
    assert "recommend_book" not in store.calls
    assert "Piranesi" not in turn.template
    assert "20%" in turn.template


def test_changed_my_mind_on_a_non_horror_book_does_neither() -> None:
    store = FakeStore(
        [_order("BLY-22002", "Circe", date(2026, 9, 11), date(2026, 9, 15), 1700, "fiction")],
        catalog=_CATALOG,
    )
    session = Session(id="conv_other", customer_id="cust_becky")
    machine = Machine(store)
    machine.step(session, "I want to return Circe", today=TODAY, now=NOW)
    turn = machine.step(session, "changed my mind", today=TODAY, now=NOW)
    names = [tool.name for tool in turn.tools]
    assert names == ["get_refund_options"]
    assert "recommend_book" not in store.calls
    assert "issue_goodwill_discount" not in store.calls
    assert "Piranesi" not in turn.template
    assert "20%" not in turn.template
    assert "I hear you: changed my mind." in turn.template
    assert session.reason == "changed my mind"
    assert session.reason_kind == "other"
