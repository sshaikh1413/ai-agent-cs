import secrets
from datetime import date, datetime, timezone
from pathlib import Path

from bookly_support.agent.articles import ARTICLES, public_article
from bookly_support.agent.allowlist import TOOL_NAMES, ToolNotAllowed, allowed_tools, run_tool
from bookly_support.agent.discounts import DuplicateDiscount, issue_goodwill_discount
from bookly_support.agent.eligibility import is_eligible
from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.queries import (
    completed_return,
    completed_return_by_id,
    customer_discounts,
    get_order,
    get_payment_method,
    get_receipt,
    goodwill_discount,
    latest_completed_return,
    list_recent_orders,
)
from bookly_support.agent.checker import accept_draft, unsupported_facts
from bookly_support.agent.recommendations import choose_recommendation
from bookly_support.agent.resolve import longest_catalog_title
from bookly_support.agent.return_agent import receipt_download
from bookly_support.agent.label_pdf import CARRIER_NAME
from bookly_support.agent.returns import commit_return, return_permitted

ASK_TITLE_OR_DATE = "Happy to help. Do you remember the book's title, or about when you ordered it?"

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
        "lookup_catalog",
        "get_policy_article",
        "list_customer_discounts",
        "issue_parcel_label",
    )
    assert allowed_tools("identify_order") == frozenset(
        {
            "list_recent_orders",
            "get_order",
            "lookup_catalog",
            "get_policy_article",
            "list_customer_discounts",
            "issue_parcel_label",
        }
    )
    assert "start_return" not in allowed_tools("identify_order")
    assert "get_refund_options" not in allowed_tools("identify_order")
    assert "recommend_book" not in allowed_tools("identify_order")
    assert allowed_tools("ask_reason") == frozenset(
        {
            "list_recent_orders",
            "get_order",
            "lookup_catalog",
            "get_policy_article",
            "issue_parcel_label",
        }
    )
    assert allowed_tools("empathy") == frozenset(
        {"recommend_book", "lookup_catalog", "issue_parcel_label"}
    )
    assert allowed_tools("empathy", "other") == frozenset(
        {"recommend_book", "lookup_catalog", "issue_parcel_label"}
    )
    assert allowed_tools("empathy", "late_delivery") == frozenset(
        {"recommend_book", "issue_goodwill_discount", "lookup_catalog", "issue_parcel_label"}
    )
    assert "issue_goodwill_discount" not in allowed_tools("write", "late_delivery")
    assert allowed_tools("choose_destination") == frozenset(
        {
            "get_refund_options",
            "list_recent_orders",
            "get_order",
            "lookup_catalog",
            "get_policy_article",
            "issue_parcel_label",
        }
    )
    assert allowed_tools("write") == frozenset(
        {"start_return", "lookup_catalog", "issue_parcel_label"}
    )
    assert allowed_tools("done") == frozenset(
        {
            "recommend_book",
            "lookup_catalog",
            "list_recent_orders",
            "get_order",
            "get_policy_article",
            "list_customer_discounts",
            "issue_parcel_label",
        }
    )
    assert allowed_tools("closed") == frozenset({"issue_parcel_label"})


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
    assert latest_completed_return("cust_becky") == {
        "customerId": "cust_becky",
        "status": "completed",
    }
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
    assert customer_discounts("cust_becky") == {"customerId": "cust_becky"}


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
        self.last_seed: str | None = None
        self.labels: dict[str, dict] = {}
        self.customer_name = "Becky Alvarez"
        self.address = "418 Linden Street, Oakland, CA 94607"

    def return_window_days(self) -> int:
        return 30

    def list_recent_orders(self, customer_id: str) -> list[dict]:
        assert customer_id == self.customer_id
        self.calls.append("list_recent_orders")
        completed = {
            document["orderId"]
            for document in self.repo.returns.values()
            if document.get("customerId") == customer_id
            and document.get("status") == "completed"
            and isinstance(document.get("orderId"), str)
        }
        listed: list[dict] = []
        for order in self.orders:
            row = dict(order)
            if row["orderId"] in completed:
                row["completedReturn"] = True
            listed.append(row)
        return listed

    def get_order(self, customer_id: str, order_id: str, today: date) -> dict | None:
        assert customer_id == self.customer_id
        self.calls.append("get_order")
        order = next((item for item in self.orders if item["orderId"] == order_id), None)
        if order is None:
            return None
        detail = dict(order)
        delivered = detail.get("deliveredAt")
        detail["eligible"] = is_eligible(
            delivered if isinstance(delivered, datetime) else None,
            today,
            30,
        )
        detail["returnWindowDays"] = 30
        detail["policy"] = "Delivered books can be returned within 30 days."
        return detail

    def recommend_book(self, customer_id: str, seed: str) -> dict:
        assert customer_id == self.customer_id
        self.calls.append("recommend_book")
        self.last_seed = seed
        chosen = choose_recommendation(
            [order["title"] for order in self.orders],
            self.catalog,
            seed,
        )
        if chosen is None:
            return {"title": None, "genre": None, "author": None}
        return chosen

    def lookup_catalog(self, title: str) -> dict:
        self.calls.append("lookup_catalog")
        wanted = title.strip().casefold()
        for book in self.catalog:
            name = str(book.get("title") or "").strip()
            if name.casefold() != wanted:
                continue
            author = book.get("author")
            summary = book.get("summary")
            return {
                "title": name,
                "author": author.strip() if isinstance(author, str) and author.strip() else None,
                "summary": summary.strip() if isinstance(summary, str) and summary.strip() else None,
            }
        return {"title": title.strip(), "author": None, "summary": None}

    def match_catalog_title(self, text: str) -> str | None:
        titles = [str(book.get("title") or "") for book in self.catalog]
        return longest_catalog_title(text, titles)

    def policy_articles(self) -> list[dict]:
        return [dict(article) for article in ARTICLES]

    def get_policy_article(self, article_id: str) -> dict | None:
        self.calls.append("get_policy_article")
        for article in ARTICLES:
            if article["id"] == article_id:
                return public_article(article, self.return_window_days())
        return None

    def list_customer_discounts(self, customer_id: str) -> dict:
        assert customer_id == self.customer_id
        self.calls.append("list_customer_discounts")
        found: list[dict] = []
        for document in self.discounts.docs.values():
            if document.get("customerId") != customer_id:
                continue
            code = document.get("code")
            if not isinstance(code, str) or not code.strip():
                continue
            row: dict = {"code": code.strip()}
            order_id = document.get("orderId")
            if isinstance(order_id, str) and order_id.strip():
                row["orderId"] = order_id.strip()
            percent = document.get("percent")
            if isinstance(percent, int):
                row["percent"] = percent
                row["percentLabel"] = f"{percent}%"
            found.append(row)
        return {"discounts": found}

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
        sentiment: str | None = None,
        exception: bool = False,
    ) -> dict:
        assert customer_id == self.customer_id
        self.calls.append("start_return")
        order = next(item for item in self.orders if item["orderId"] == order_id)
        delivered = order.get("deliveredAt")
        eligible = is_eligible(delivered if isinstance(delivered, datetime) else None, today, 30)
        if not return_permitted(eligible=eligible, destination=destination, exception=exception):
            return {
                "status": "not_completed",
                "reason": "ineligible",
                "orderId": order_id,
                "title": order["title"],
            }
        card = destination == "original_payment"
        exception_write = exception and destination == "store_credit"
        result = commit_return(
            self.repo,
            customer_id=customer_id,
            order_id=order_id,
            destination=destination,
            title=order["title"],
            amount_cents=int(order["refundableCents"]),
            brand="Visa" if card else None,
            last4="4242" if card else None,
            now=now,
            new_ids=lambda: ("ret_fixed", "rcpt_fixed"),
            reason=reason,
            reason_kind=reason_kind,
            sentiment=sentiment,
            exception=exception_write,
            tracking_number="BKLY18440TEST" if exception_write else None,
            carrier=CARRIER_NAME if exception_write else None,
            label_id="lbl_fixed" if exception_write else None,
        )
        if result.get("status") == "completed" and result.get("exception"):
            result["address"] = self.address
            self.labels[str(result["labelId"])] = {
                "_id": result["labelId"],
                "customerId": customer_id,
                "returnId": result["returnId"],
                "orderId": order_id,
                "trackingNumber": result["trackingNumber"],
                "carrier": result["carrier"],
                "name": self.customer_name,
                "address": self.address,
            }
        return result

    def issue_parcel_label(
        self,
        customer_id: str,
        return_id: str | None = None,
        order_id: str | None = None,
    ) -> dict:
        assert customer_id == self.customer_id
        self.calls.append("issue_parcel_label")
        document = None
        if isinstance(return_id, str) and return_id.strip():
            found = self.repo.returns.get(return_id.strip())
            if (
                found is not None
                and found.get("customerId") == customer_id
                and found.get("status") == "completed"
            ):
                document = found
        if document is None and isinstance(order_id, str) and order_id.strip():
            document = self.repo.find_completed_return(customer_id, order_id.strip())
        if document is None:
            return {"status": "none"}
        tracking = document.get("trackingNumber")
        carrier = document.get("carrier")
        label_id = document.get("labelId")
        ready = (
            isinstance(tracking, str)
            and tracking.strip()
            and isinstance(carrier, str)
            and carrier.strip()
            and isinstance(label_id, str)
            and label_id.strip()
        )
        if ready:
            tracking = tracking.strip()
            carrier = carrier.strip()
            label_id = label_id.strip()
        else:
            tracking = f"BKLY{secrets.token_hex(5).upper()}"
            carrier = CARRIER_NAME
            label_id = f"lbl_{secrets.token_hex(6)}"
            document["trackingNumber"] = tracking
            document["carrier"] = carrier
            document["labelId"] = label_id
        receipt = self.repo.receipts.get(document.get("receiptId"))
        title = receipt["title"] if isinstance(receipt, dict) and receipt.get("title") else "this book"
        self.labels[label_id] = {
            "_id": label_id,
            "customerId": customer_id,
            "returnId": document["_id"],
            "orderId": document["orderId"],
            "trackingNumber": tracking,
            "carrier": carrier,
            "name": self.customer_name,
            "address": self.address,
        }
        return {
            "status": "ready",
            "labelId": label_id,
            "trackingNumber": tracking,
            "carrier": carrier,
            "returnId": document["_id"],
            "orderId": document["orderId"],
            "title": title,
            "receiptId": document.get("receiptId"),
            "address": self.address,
        }


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
    assert [choice.title for choice in first.choices] == ["The Midnight Library", "Circe"]
    assert "The Midnight Library" not in first.template
    assert "Circe" not in first.template
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
    assert stored["sentiment"] == "neutral"
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
    assert {choice.order_id for choice in turn.choices} == {"BLY-22018", "BLY-22019"}


def test_closed_window_does_not_offer_a_refund() -> None:
    store = FakeStore(
        [_order("BLY-11004", "Old Book", date(2026, 8, 1), date(2026, 8, 2), 1000)]
    )
    session = Session(id="conv_test", customer_id="cust_becky")
    turn = Machine(store).step(session, "I want to return BLY-11004", today=TODAY, now=NOW)
    assert "get_refund_options" not in [tool.name for tool in turn.tools]
    assert "start_return" not in store.calls
    assert "30-day" in turn.template
    assert "cannot go back on the card" in turn.template
    assert "What is the reason for the return?" in turn.template
    assert session.phase == "exception_why"
    assert session.order_id == "BLY-11004"
    assert session.reason is None


_CATALOG = [
    {
        "title": "The Haunting of Hill House",
        "genre": "horror",
        "author": "Shirley Jackson",
        "summary": "Four guests stay in a house that keeps the one who most wants to belong.",
    },
    {
        "title": "Mexican Gothic",
        "genre": "horror",
        "author": "Silvia Moreno-Garcia",
        "summary": "A woman travels to a remote Mexican house and finds the family bound to the walls.",
    },
    {
        "title": "Piranesi",
        "genre": "fantasy",
        "author": "Susanna Clarke",
        "summary": "A man records the tides in a house of statues.",
    },
    {
        "title": "Project Hail Mary",
        "genre": "science fiction",
        "author": "Andy Weir",
        "summary": "A teacher wakes alone on a ship and has to learn why the sun is dimming.",
    },
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
    expected = choose_recommendation(["Mexican Gothic"], _CATALOG, "BLY-22044")
    assert expected is not None
    assert expected["genre"].casefold() != "horror"
    assert turn.tools[0].payload["title"] == expected["title"]
    assert "wasn't scary enough" in turn.template
    assert expected["title"] in turn.template
    stocked = next(book for book in _CATALOG if book["title"] == expected["title"])
    assert stocked["summary"] not in turn.template
    assert stocked["author"] not in turn.template
    assert "really sorry" in turn.template
    assert "20%" not in turn.template
    assert session.phase == "choose_destination"
    assert session.reason_kind == "other"
    # VADER called this positive. Claude's label is negative: she was disappointed.
    assert session.sentiment == "negative"


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
    assert "20%" in turn.required
    assert code in turn.required
    assert "Piranesi" not in turn.template
    assert "birthday" in turn.template.lower()
    assert "gift" in turn.template.lower()
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
    assert "Plans change." in turn.template
    assert "I hear you" not in turn.template
    assert "changed my mind" not in turn.template
    assert session.reason == "changed my mind"
    assert session.reason_kind == "other"
    assert session.sentiment == "neutral"


def _bob_late_turn(reason: str):
    store = FakeStore(
        [_order("BLY-33010", "A Gentleman in Moscow", date(2026, 9, 12), date(2026, 9, 28), 1800, "fiction")],
        customer_id="cust_bob",
        catalog=_CATALOG,
    )
    session = Session(id="conv_bob_reason", customer_id="cust_bob")
    machine = Machine(store)
    machine.step(session, "I want to return A Gentleman in Moscow", today=TODAY, now=NOW)
    turn = machine.step(session, reason, today=TODAY, now=NOW)
    return turn


def test_late_apology_follows_the_reason_and_rejects_an_invented_gift() -> None:
    bob = "dont need it anymore. delivery too late"
    turn = _bob_late_turn(bob)
    code = turn.tools[0].payload["code"]
    assert turn.payload["reason"] == bob
    assert "20%" in turn.template
    assert code in turn.template
    assert "20%" in turn.required
    assert code in turn.required
    assert "arrived late" in turn.template
    # Their sentence is acknowledged, not repeated back to them.
    assert "dont need it anymore" not in turn.template
    assert "delivery too late" not in turn.template
    assert "gift" not in turn.template.lower()
    assert "birthday" not in turn.template.lower()
    assert "missed gift" not in turn.instruction.lower()
    assert "actually said" in turn.instruction
    drafted = turn.template.replace("arrived late", "arrived late and the gift was missed", 1)
    assert "gift" in drafted.lower()
    assert "gift" in "".join(unsupported_facts(drafted, turn.payload)).lower()
    accepted = accept_draft(drafted, turn.template, turn.payload, turn.required)
    assert accepted == turn.template
    assert "gift" not in accepted.lower()

    birthday = _bob_late_turn("It was a birthday gift and it arrived late")
    birthday_code = birthday.tools[0].payload["code"]
    assert "gift" in birthday.template.lower()
    assert "birthday" in birthday.template.lower()
    assert "20%" in birthday.template
    assert birthday_code in birthday.template
    assert "20%" in birthday.required
    assert birthday_code in birthday.required
    missed = birthday.template.replace(
        "arrived late",
        "arrived late and the birthday gift was missed",
        1,
    )
    assert unsupported_facts(missed, birthday.payload) == []
    assert accept_draft(missed, birthday.template, birthday.payload, birthday.required) == missed


def test_negative_late_delivery_still_discounts_and_does_not_recommend() -> None:
    store = FakeStore(
        [_order("BLY-33010", "A Gentleman in Moscow", date(2026, 9, 12), date(2026, 9, 28), 1800, "fiction")],
        customer_id="cust_bob",
        catalog=_CATALOG,
    )
    session = Session(id="conv_angry", customer_id="cust_bob")
    machine = Machine(store)
    machine.step(session, "I want to return A Gentleman in Moscow", today=TODAY, now=NOW)
    turn = machine.step(
        session,
        "This awful late delivery ruined everything and I hated it",
        today=TODAY,
        now=NOW,
    )
    assert session.sentiment == "negative"
    assert session.reason_kind == "late_delivery"
    assert [tool.name for tool in turn.tools] == ["issue_goodwill_discount", "get_refund_options"]
    assert "recommend_book" not in store.calls
    assert "really sorry" in turn.template
    assert "20%" in turn.template


def test_negative_sentiment_is_stored_on_the_completed_return() -> None:
    store = FakeStore(
        [_order("BLY-22002", "Circe", date(2026, 9, 11), date(2026, 9, 15), 1700, "fiction")],
        catalog=_CATALOG,
    )
    session = Session(id="conv_feel", customer_id="cust_becky")
    machine = Machine(store)
    reason = "This book was awful and I hated every page."
    machine.step(session, "I want to return Circe", today=TODAY, now=NOW)
    asked = machine.step(session, reason, today=TODAY, now=NOW)
    assert session.sentiment == "negative"
    assert "really sorry" in asked.template
    assert "recommend_book" not in store.calls
    assert "issue_goodwill_discount" not in store.calls
    assert store.repo.returns == {}
    machine.step(session, "store credit", today=TODAY, now=NOW)
    stored = next(iter(store.repo.returns.values()))
    assert stored["reason"] == reason
    assert stored["reasonKind"] == "other"
    assert stored["sentiment"] == "negative"


def test_done_phase_recommendation_replies_with_only_that_title() -> None:
    store = FakeStore(
        [_order("BLY-22044", "Mexican Gothic", date(2026, 9, 30), date(2026, 10, 1), 1699, "horror")],
        catalog=_CATALOG,
    )
    session = Session(
        id="conv_done",
        customer_id="cust_becky",
        phase="done",
        order_id="BLY-22044",
        title="Mexican Gothic",
        genre="horror",
    )
    turn = Machine(store).step(session, "do you recommend any books for me?", today=TODAY, now=NOW)
    assert [tool.name for tool in turn.tools] == ["recommend_book"]
    assert store.last_seed == "BLY-22044"
    title = turn.tools[0].payload["title"]
    expected = choose_recommendation(["Mexican Gothic"], _CATALOG, "BLY-22044")
    assert expected is not None
    assert title == expected["title"]
    assert turn.template == title
    assert turn.tools[0].payload.get("summary") is None
    for book in _CATALOG:
        if book["title"] != title:
            assert book["title"] not in turn.template
    assert session.phase == "done"
    other = next(
        book["title"]
        for book in _CATALOG
        if book["title"] != title and book["genre"] != "horror"
    )
    draft = f"You might enjoy {other} instead."
    assert accept_draft(draft, turn.template, turn.payload, turn.required) == turn.template


def test_done_phase_without_an_order_seeds_the_pick_from_the_customer() -> None:
    store = FakeStore([], catalog=_CATALOG, customer_id="cust_becky")
    session = Session(id="conv_done", customer_id="cust_becky", phase="done")
    turn = Machine(store).step(session, "do you recommend any books for me?", today=TODAY, now=NOW)
    expected = choose_recommendation([], _CATALOG, "cust_becky")
    assert store.last_seed == "cust_becky"
    assert expected is not None
    assert turn.template == expected["title"]
    assert session.phase == "done"


def test_done_phase_with_nothing_left_names_no_book() -> None:
    catalog = [
        {"title": "The Shining", "genre": "horror"},
        {"title": "Mexican Gothic", "genre": "horror"},
    ]
    store = FakeStore(
        [_order("BLY-22044", "Mexican Gothic", date(2026, 9, 30), date(2026, 10, 1), 1699, "horror")],
        catalog=catalog,
    )
    session = Session(id="conv_done", customer_id="cust_becky", phase="done", order_id="BLY-22044")
    turn = Machine(store).step(session, "Can you suggest a book?", today=TODAY, now=NOW)
    assert [tool.name for tool in turn.tools] == ["recommend_book"]
    assert turn.tools[0].payload["title"] is None
    assert "The Shining" not in turn.template
    assert "Mexican Gothic" not in turn.template
    assert "don't have another title" in turn.template
    assert accept_draft("Try Piranesi.", turn.template, turn.payload, turn.required) == turn.template


def test_done_phase_goodbye_closes_and_other_questions_do_not_recommend() -> None:
    store = FakeStore(
        [_order("BLY-22044", "Mexican Gothic", date(2026, 9, 30), date(2026, 10, 1), 1699, "horror")],
        catalog=_CATALOG,
    )
    session = Session(id="conv_done", customer_id="cust_becky", phase="done", order_id="BLY-22044")
    machine = Machine(store)
    hours = machine.step(session, "What are your store hours?", today=TODAY, now=NOW)
    assert hours.tools == []
    assert "recommend_book" not in store.calls
    assert "anything else" in hours.template
    assert session.phase == "done"
    closed = machine.step(session, "no thanks", today=TODAY, now=NOW)
    assert closed.tools == []
    assert "recommend_book" not in store.calls
    assert session.phase == "closed"


def test_thats_the_one_selects_bobs_single_shown_order() -> None:
    """The old loop asked which order again. One shown order is enough."""

    phrases = (
        "that's the one",
        "thats the one",
        "that one",
        "yes that one",
        "yes that's the one",
    )

    def bob_store() -> FakeStore:
        return FakeStore(
            [
                _order(
                    "BLY-33010",
                    "A Gentleman in Moscow",
                    date(2026, 9, 12),
                    date(2026, 9, 28),
                    1800,
                    "fiction",
                )
            ],
            customer_id="cust_bob",
        )

    for phrase in phrases:
        store = bob_store()
        session = Session(id="conv_bob", customer_id="cust_bob")
        machine = Machine(store)
        shown = machine.step(session, "I want to return a product", today=TODAY, now=NOW)
        assert session.phase == "identify_order"
        assert session.order_id is None
        assert [choice.order_id for choice in shown.choices] == ["BLY-33010"]
        assert "Which book" in shown.template
        assert "BLY-33010" not in shown.template

        picked = machine.step(session, phrase, today=TODAY, now=NOW)
        assert [tool.name for tool in picked.tools] == ["list_recent_orders", "get_order"]
        assert session.phase == "ask_reason"
        assert session.order_id == "BLY-33010"
        assert "A Gentleman in Moscow" in picked.template
        assert "What made you want to send it back?" in picked.template
        assert "Which one" not in picked.template
        assert "start_return" not in store.calls
        assert "get_refund_options" not in store.calls

    listed = FakeStore(
        [
            _order("BLY-33010", "A Gentleman in Moscow", date(2026, 9, 12), date(2026, 9, 28), 1800),
            _order("BLY-33011", "Piranesi", date(2026, 9, 20), date(2026, 9, 22), 1600),
        ],
        customer_id="cust_bob",
    )
    session = Session(id="conv_two", customer_id="cust_bob")
    machine = Machine(listed)
    first = machine.step(session, "I want to return a product", today=TODAY, now=NOW)
    assert {choice.order_id for choice in first.choices} == {"BLY-33010", "BLY-33011"}
    assert first.template == ASK_TITLE_OR_DATE
    assert first.read_choices is False
    assert "BLY-33010" not in first.template
    assert "BLY-33011" not in first.template
    again = machine.step(session, "that's the one", today=TODAY, now=NOW)
    assert [tool.name for tool in again.tools] == ["list_recent_orders"]
    assert session.phase == "identify_order"
    assert session.order_id is None
    assert "Which book" in again.template
    assert {choice.order_id for choice in again.choices} == {"BLY-33010", "BLY-33011"}
    assert "BLY-33010" not in again.template
    assert "BLY-33011" not in again.template
    assert "What made you want to send it back?" not in again.template
    assert "get_order" not in listed.calls


def test_which_order_turn_offers_a_choice_per_order_without_reading_every_title() -> None:
    packing = {
        "orderId": "BLY-44120",
        "title": "Klara and the Sun",
        "placedAt": datetime(2026, 10, 1, 14, tzinfo=timezone.utc),
        "status": "packing",
        "refundableCents": 1700,
        "paymentMethodId": "pm_becky_visa",
    }
    store = FakeStore(
        [
            _order("BLY-44121", "The Night Circus", date(2026, 9, 20), date(2026, 9, 28), 1800),
            packing,
            _order("BLY-22044", "Mexican Gothic", date(2026, 8, 1), date(2026, 8, 5), 1699),
        ]
    )
    machine = Machine(store)
    session = Session(id="conv_choices", customer_id="cust_becky")
    turn = machine.step(session, "I want to return a product", today=TODAY, now=NOW)
    assert [choice.order_id for choice in turn.choices] == ["BLY-44121", "BLY-44120", "BLY-22044"]
    assert [choice.title for choice in turn.choices] == [
        "The Night Circus",
        "Klara and the Sun",
        "Mexican Gothic",
    ]
    assert [choice.mark for choice in turn.choices] == [
        "Delivered and inside the 30-day window",
        "Still on the way, packing",
        "Delivered and past the 30-day window",
    ]
    payload_orders = turn.tools[0].payload["orders"]
    assert [order["orderId"] for order in payload_orders] == [choice.order_id for choice in turn.choices]
    assert [order["mark"] for order in payload_orders] == [choice.mark for choice in turn.choices]
    for title in ("The Night Circus", "Klara and the Sun", "Mexican Gothic"):
        assert title not in turn.template
    for order_id in ("BLY-44121", "BLY-44120", "BLY-22044"):
        assert order_id not in turn.template
    assert turn.template == ASK_TITLE_OR_DATE
    invented = f"{turn.template} Circe, order BLY-99999."
    assert unsupported_facts(invented, turn.payload)
    assert accept_draft(invented, turn.template, turn.payload, turn.required) == turn.template

    clicked = machine.step(session, turn.choices[0].order_id, today=TODAY, now=NOW)
    assert session.order_id == "BLY-44121"
    assert clicked.choices == []
    assert "What made you want to send it back?" in clicked.template

    typed_session = Session(id="conv_typed", customer_id="cust_becky")
    machine.step(typed_session, "I want to return a product", today=TODAY, now=NOW)
    typed = machine.step(typed_session, "Mexican Gothic", today=TODAY, now=NOW)
    assert typed_session.order_id == "BLY-22044"
    assert typed.choices == []
    assert "Mexican Gothic" in typed.template
