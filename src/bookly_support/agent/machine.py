"""Return conversation. The machine picks the tool. Claude does not."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from bookly_support.agent.allowlist import run_tool
from bookly_support.agent.reasons import classify_reason
from bookly_support.agent.eligibility import is_eligible
from bookly_support.agent.resolve import (
    accepts_store_credit_exception,
    asked_title,
    asks_for_recommendation,
    asks_order_status,
    asks_too_late,
    book_question,
    hedges_store_credit_exception,
    confirms_shown_order,
    destination_choice,
    is_decline,
    is_password_reset,
    is_in_progress,
    named_orders,
    resolve_order,
    resolve_status,
    wants_return_in_play,
)
from bookly_support.agent.window import iso_day, spoken_date
from bookly_support.agent.sentiment import label_sentiment
from bookly_support.agent.templates import (
    about_book,
    ask_anything_else,
    ask_reason,
    ask_what_happened,
    closed,
    completed,
    empathy_horror,
    empathy_horror_plain,
    empathy_late,
    empathy_other,
    delivered_window_list,
    exception_completed,
    exception_confirm,
    exception_offer,
    late_apology,
    list_orders,
    missing_order,
    no_order_in_progress,
    not_completed,
    order_status,
    order_status_choices,
    outside_window,
    password_refused,
    past_window_why,
    recommend_reply,
    refund_choice,
    still_sending,
    week_ambiguous,
    week_none,
)


class ReturnStore(Protocol):
    def return_window_days(self) -> int:
        """How many days the policy keeps a delivered book eligible."""

    def list_recent_orders(self, customer_id: str) -> list[dict]:
        """Recent orders for this customer, newest first."""

    def get_order(self, customer_id: str, order_id: str, today: date) -> dict | None:
        """One order, with eligibility, or None."""

    def get_refund_options(self, customer_id: str, order_id: str) -> dict | None:
        """Refund destinations for an order on this account."""

    def recommend_book(self, customer_id: str, seed: str) -> dict:
        """One non-horror title this customer does not already own."""

    def lookup_catalog(self, title: str) -> dict:
        """Author and summary for a catalog title, or nulls when there is no row."""

    def match_catalog_title(self, text: str) -> str | None:
        """The catalog title named in this message, or None."""

    def issue_goodwill_discount(self, customer_id: str, order_id: str, now: datetime) -> dict:
        """One 20% code for this customer and order, or the code already stored."""

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
        """Write the return, or return the receipt already stored."""


@dataclass
class ToolTrace:
    name: str
    summary: str
    payload: dict


@dataclass
class Session:
    id: str
    customer_id: str
    phase: str = "identify_order"
    order_id: str | None = None
    destination: str | None = None
    return_id: str | None = None
    closed_at: datetime | None = None
    reason: str | None = None
    reason_kind: str | None = None
    sentiment: str | None = None
    title: str | None = None
    genre: str | None = None
    recommended_title: str | None = None
    exception: bool = False


@dataclass(frozen=True)
class OrderChoice:
    """One book the customer can click. Copied from the tool payload."""

    order_id: str
    title: str
    mark: str


@dataclass
class Turn:
    template: str
    instruction: str
    tools: list[ToolTrace] = field(default_factory=list)
    intent: str = "return_refund"
    required: list[str] = field(default_factory=list)
    step: str = "Step: which order"
    customer_reason: str | None = None
    choices: list[OrderChoice] = field(default_factory=list)

    @property
    def payload(self) -> dict:
        """Tool facts for phrasing. A late delivery also includes the reason they typed."""

        body: dict = {"results": [tool.payload for tool in self.tools]}
        if isinstance(self.customer_reason, str):
            body["reason"] = self.customer_reason.strip()
        return body


class Machine:
    def __init__(self, store: ReturnStore) -> None:
        self._store = store

    def step(self, session: Session, message: str, *, today: date, now: datetime) -> Turn:
        kind = book_question(message)
        subject = _about_subject(self._store, session, message) if kind else None
        if kind and subject and session.phase != "closed":
            return self._about(session, subject, kind)
        if session.phase not in {"write", "empathy", "closed"} and asks_order_status(message):
            return self._status(session, message, today)
        if session.phase == "done":
            return self._done(session, message, now)
        if session.phase == "write":
            return self._write(session, today, now)
        if session.phase == "choose_destination":
            return self._choose(session, message, today, now)
        if session.phase == "ask_reason":
            return self._reason(session, message, today, now)
        if session.phase == "empathy":
            return self._empathy_and_offer(session, today, now)
        if session.phase == "which_book":
            return self._which_book(session, message, today, now)
        if session.phase == "exception_why":
            return self._exception_why(session, message, today, now)
        if session.phase == "exception_offer":
            return self._exception_offer(session, message, today, now)
        return self._identify(session, message, today, now)

    def _done(self, session: Session, message: str, now: datetime) -> Turn:
        if session.exception and accepts_store_credit_exception(message):
            session.destination = "store_credit"
            session.phase = "write"
            return self._write(session, now.date(), now)
        if is_decline(message):
            session.phase = "closed"
            session.closed_at = now
            return Turn(
                template=closed(),
                instruction="They are done. Close the chat in one short English sentence. Do not mention orders, money, dates, or cards.",
                intent="clarify",
                step="Step: close",
            )
        if asks_for_recommendation(message):
            return self._recommend(session)
        return Turn(
            template=ask_anything_else(),
            instruction="Ask if they need help with anything else. Do not mention orders, money, dates, or cards.",
            intent="clarify",
            step="Step: anything else",
        )

    def _recommend(self, session: Session) -> Turn:
        seed = session.order_id or session.customer_id
        recommendation = run_tool(
            "done",
            "recommend_book",
            lambda: self._store.recommend_book(session.customer_id, seed),
        )
        title = recommendation.get("title")
        _remember_recommendation(session, recommendation)
        if isinstance(title, str) and title.strip():
            instruction = (
                "Reply with only the title in the JSON. "
                "Do not invent a book title. Do not name any other book. "
                "Do not add the author or the summary."
            )
            required = [title.strip()]
        else:
            instruction = "Say there is no title to suggest. Do not name a book."
            required = []
        return Turn(
            template=recommend_reply(recommendation),
            instruction=instruction,
            tools=[
                ToolTrace(
                    name="recommend_book",
                    summary=(
                        f"Suggested {title}."
                        if isinstance(title, str) and title.strip()
                        else "No non-horror title was available."
                    ),
                    payload=recommendation,
                )
            ],
            required=required,
            step="Step: offer a non-horror title",
        )

    def _identify(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        if is_password_reset(message):
            return Turn(
                template=password_refused(),
                instruction="Say, in English, that this desk can help with a return and cannot reset a password.",
                intent="out_of_scope",
            )
        if asks_too_late(message):
            return self._too_late(session, message, today, now)

        orders = run_tool(
            session.phase,
            "list_recent_orders",
            lambda: self._store.list_recent_orders(session.customer_id),
        )
        listed = ToolTrace(
            name="list_recent_orders",
            summary=f"Listed {len(orders)} recent orders.",
            payload={"orders": [_public_order(order) for order in orders]},
        )
        kind, matches = resolve_order(message, orders, today)
        if kind == "week_none":
            if not orders:
                return Turn(
                    template=week_none([]),
                    instruction=(
                        "No order was placed about a week ago, and there is nothing recent to return. "
                        "Say so. Do not invent an order."
                    ),
                    tools=[listed],
                )
            return self._ask_to_choose(
                listed,
                orders,
                today,
                week_none(orders),
                (
                    "No order was placed about a week ago. "
                    "Ask which book they want, in one short question. "
                    "Do not read the titles or the order ids. "
                    "Do not invent an order. Do not say a return has started."
                ),
            )
        if kind == "ambiguous":
            return self._ask_to_choose(
                listed,
                matches,
                today,
                week_ambiguous(matches) if _is_week_ask(message) else list_orders(matches),
                (
                    "More than one order matches. "
                    "Ask which one they want, in one short question. "
                    "Do not read the titles or the order ids. "
                    "Do not invent an order. Do not say a return has started."
                ),
            )
        if kind != "selected":
            if not orders:
                return Turn(
                    template=list_orders([]),
                    instruction="There is nothing recent to return. Say so. Do not invent an order.",
                    tools=[listed],
                )
            return self._ask_to_choose(
                listed,
                orders,
                today,
                list_orders(orders),
                (
                    "They want to return a product. "
                    "Ask which book they want to return, in one short question. "
                    "Do not read the titles or the order ids. "
                    "Do not invent an order. Do not say a return has started."
                ),
            )

        selected = matches[0]
        detail = run_tool(
            session.phase,
            "get_order",
            lambda: self._store.get_order(session.customer_id, selected["orderId"], today),
        )
        if detail is None:
            return Turn(
                template=missing_order(),
                instruction="The order is not on this account. Say so. Do not invent an order.",
                tools=[listed],
            )
        opened = ToolTrace(
            name="get_order",
            summary=f"Opened {detail['orderId']}.",
            payload=_public_order(detail) | {
                "eligible": detail["eligible"],
                "returnWindowDays": detail["returnWindowDays"],
                "policy": detail["policy"],
            },
        )
        if not detail["eligible"]:
            if not _is_delivered(detail):
                status = detail.get("status")
                required = [detail["title"], detail["orderId"]]
                if isinstance(status, str) and status.strip():
                    required.append(status.strip())
                opened.payload.pop("policy", None)
                return Turn(
                    template=still_sending(detail),
                    instruction=(
                        "This order has not been delivered. Repeat the stored status from the JSON. "
                        "Do not start a return. Do not say it is past the return window."
                    ),
                    tools=[opened],
                    required=required,
                )
            self._remember_exception(session, detail)
            opened.payload["window"] = "past"
            opened.payload["storeCreditOnly"] = True
            opened.payload["cardOffered"] = False
            return Turn(
                template=outside_window(opened.payload),
                instruction=(
                    "This book is outside the return window, so it cannot go back on the card. "
                    "Ask what happened with it. Stay on this order. "
                    "Do not list other orders. Do not offer store credit, the Visa, or any amount yet."
                ),
                tools=[opened],
                required=[detail["title"], detail["orderId"], str(detail["returnWindowDays"])],
                step="Step: what happened",
            )

        return self._ask_why(session, detail, [listed, opened])

    def _reason(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        if is_password_reset(message):
            return Turn(
                template=password_refused(),
                instruction="Say, in English, that this desk can help with a return and cannot reset a password.",
                intent="out_of_scope",
                step="Step: why it's coming back",
            )
        if session.order_id is None or not session.title:
            session.phase = "identify_order"
            return self._identify(session, message, today, now)
        session.reason = message.strip()
        session.reason_kind = classify_reason(session.reason)
        session.sentiment = label_sentiment(session.reason)
        session.phase = "empathy"
        return self._empathy_and_offer(session, today, now)

    def _empathy_and_offer(self, session: Session, today: date, now: datetime) -> Turn:
        del today
        if session.reason_kind is None and session.reason:
            session.reason_kind = classify_reason(session.reason)
        if session.sentiment is None and session.reason is not None:
            session.sentiment = label_sentiment(session.reason)
        title = session.title or "this book"
        sentiment = session.sentiment
        traces: list[ToolTrace] = []
        lead = ""
        instruction = ""
        extra_required: list[str] = []
        late = session.reason_kind == "late_delivery"
        if late:
            discount = run_tool(
                "empathy",
                "issue_goodwill_discount",
                lambda: self._store.issue_goodwill_discount(
                    session.customer_id,
                    session.order_id or "",
                    now,
                ),
                reason_kind=session.reason_kind,
            )
            traces.append(
                ToolTrace(
                    name="issue_goodwill_discount",
                    summary=f"Goodwill code {discount.get('code')} for {discount.get('orderId')}.",
                    payload=discount,
                )
            )
            reason = session.reason or ""
            if discount.get("percentLabel") and discount.get("code"):
                lead = empathy_late(title, discount, reason, sentiment)
                extra_required = [str(discount["percentLabel"]), str(discount["code"])]
            else:
                lead = late_apology(title, reason, sentiment)
            instruction = (
                f"{_tone_clause(sentiment)} "
                "Apologize for what the customer actually said in the reason, plus the late delivery. "
                "Mention a gift or a birthday only when those words are in the reason. "
                "Copy 20% and the discount code from the JSON. "
                "Do not recommend a book. Do not invent a percent or a code."
            )
        elif session.genre == "horror":
            recommendation = run_tool(
                "empathy",
                "recommend_book",
                lambda: self._store.recommend_book(
                    session.customer_id,
                    session.order_id or session.customer_id,
                ),
                reason_kind=session.reason_kind,
            )
            traces.append(
                ToolTrace(
                    name="recommend_book",
                    summary=(
                        f"Suggested {recommendation['title']}."
                        if recommendation.get("title")
                        else "No non-horror title was available."
                    ),
                    payload=recommendation,
                )
            )
            _remember_recommendation(session, recommendation)
            if recommendation.get("title"):
                lead = empathy_horror(title, recommendation, sentiment)
                extra_required = [str(recommendation["title"])]
            else:
                lead = empathy_horror_plain(title, sentiment)
            instruction = (
                f"{_tone_clause(sentiment)} "
                "Apologize that it was not a good read and not scary. "
                "Recommend only the title in the JSON. "
                "Do not mention a discount, a percent, or a code. "
                "Do not invent a book title."
            )
        else:
            lead = empathy_other(title, session.reason or "", sentiment)
            instruction = (
                f"{_tone_clause(sentiment)} "
                "Show empathy from the customer's reason and the book title. "
                "Do not recommend a book. Do not mention a discount, a percent, or a code. "
                "Do not invent a book title."
            )
        session.phase = "choose_destination"
        offer = self._offer(session, traces)
        offer.template = f"{lead} {offer.template}"
        offer.instruction = f"{instruction} {offer.instruction}"
        offer.required = [*extra_required, *offer.required]
        offer.step = _offer_step(session, traces)
        if late:
            offer.customer_reason = session.reason or ""
        return offer

    def _status(self, session: Session, message: str, today: date) -> Turn:
        """Answer from the status stored on the order. Do not start a return."""

        orders = run_tool(
            session.phase,
            "list_recent_orders",
            lambda: self._store.list_recent_orders(session.customer_id),
        )
        kind, chosen = resolve_status(message, orders)
        if kind == "missing":
            return Turn(
                template=missing_order(),
                instruction=(
                    "The order is not on this account. Say so. "
                    "Do not invent an order id, a status, or a place. Do not start a return."
                ),
                intent="order_status",
                step="Step: order status",
            )
        if kind == "none":
            return Turn(
                template=no_order_in_progress(),
                instruction=(
                    "No order is still being sent. Say so. "
                    "Do not invent an order id, a status, or a place. Do not start a return."
                ),
                tools=[
                    ToolTrace(
                        name="list_recent_orders",
                        summary="No order is still being sent.",
                        payload={"orders": []},
                    )
                ],
                intent="order_status",
                step="Step: order status",
            )
        if kind == "several":
            public = [_status_facts(order) for order in chosen]
            marked = [_marked_order(order, today, self._store.return_window_days()) for order in chosen]
            choice_rows = _choice_list(marked)
            return Turn(
                template=order_status_choices(public),
                instruction=(
                    "More than one order matches. Name each order id, title, and status "
                    "from the JSON, and ask which order. Copy each status detail. "
                    "Do not invent a status or a place. Do not start a return."
                ),
                tools=[
                    ToolTrace(
                        name="list_recent_orders",
                        summary=f"Listed {len(public)} orders for a status question.",
                        payload={
                            "orders": public,
                            "choices": [_choice_payload(choice) for choice in choice_rows],
                        },
                    )
                ],
                intent="order_status",
                required=_status_required(public),
                step="Step: order status",
                choices=choice_rows,
            )

        selected = chosen[0]
        detail = run_tool(
            session.phase,
            "get_order",
            lambda: self._store.get_order(session.customer_id, selected["orderId"], today),
        )
        if detail is None:
            return Turn(
                template=missing_order(),
                instruction="The order is not on this account. Say so. Do not invent an order or a status.",
                intent="order_status",
                step="Step: order status",
            )
        facts = _status_facts(detail)
        return Turn(
            template=order_status(facts),
            instruction=(
                "They asked where the order is. Copy the status and the status detail from the JSON. "
                "Include that order id and title. "
                "Do not name a status, an order id, or a place that is not in the JSON. "
                "Do not start a return."
            ),
            tools=[
                ToolTrace(
                    name="get_order",
                    summary=f"Status for {facts['orderId']}.",
                    payload=facts,
                )
            ],
            intent="order_status",
            required=_status_required([facts]),
            step="Step: order status",
        )

    def _about(self, session: Session, title: str, kind: str) -> Turn:
        book = run_tool(
            session.phase,
            "lookup_catalog",
            lambda: self._store.lookup_catalog(title),
        )
        author = book.get("author") if isinstance(book.get("author"), str) else None
        summary = book.get("summary") if isinstance(book.get("summary"), str) else None
        required: list[str] = []
        if kind in {"author", "both"} and author and author.strip():
            required.append(author.strip())
        if kind in {"summary", "both"} and summary and summary.strip():
            required.append(summary.strip())
        if kind == "author":
            instruction = (
                "They asked who the author is. Copy the author from the JSON and no one else. "
                "Do not add the summary. If author is null, say you do not have that. "
                "Do not invent an author or a plot."
            )
        elif kind == "summary":
            instruction = (
                "They asked what the book is about. Copy the summary from the JSON. "
                "Do not paraphrase it and do not add an author. "
                "If summary is null, say you do not have that. "
                "Do not invent an author or a plot."
            )
        else:
            instruction = (
                "They asked for the author and what the book is about. "
                "Copy the author and the summary from the JSON. "
                "If either is null, say you do not have that part. "
                "Do not invent an author or a plot."
            )
        return Turn(
            template=about_book(book, kind),
            instruction=instruction,
            tools=[
                ToolTrace(
                    name="lookup_catalog",
                    summary=f"Catalog facts for {book.get('title') or title}.",
                    payload=book,
                )
            ],
            required=required,
            step="Step: about this book",
        )

    def _choose(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        choice = destination_choice(message)
        if choice is None or session.order_id is None:
            return self._offer(session, [])
        session.destination = choice
        session.phase = "write"
        return self._write(session, today, now)

    def _offer(self, session: Session, prior: list[ToolTrace]) -> Turn:
        if session.order_id is None:
            raise RuntimeError("refund options require an order")
        options = run_tool(
            session.phase,
            "get_refund_options",
            lambda: self._store.get_refund_options(session.customer_id, session.order_id or ""),
        )
        if options is None:
            session.phase = "identify_order"
            session.order_id = None
            return Turn(
                template=missing_order(),
                instruction="The order is not on this account. Say so.",
                tools=prior,
            )
        offered = ToolTrace(
            name="get_refund_options",
            summary=f"Refund options for {options['orderId']}.",
            payload=options,
        )
        required = [options["title"], options["orderId"], options["amount"], "credit"]
        original = options.get("originalPayment") or {}
        if original.get("available") and original.get("last4"):
            required.append(str(original["last4"]))
        return Turn(
            template=refund_choice(options),
            instruction=(
                "Offer the refund destinations in the JSON. Ask them to choose original payment "
                "or store credit. Do not say the return is complete or that it has started."
            ),
            tools=[*prior, offered],
            required=required,
            step="Step: Visa or store credit",
        )

    def _write(self, session: Session, today: date, now: datetime) -> Turn:
        if session.order_id is None or session.destination is None:
            session.phase = "choose_destination"
            return self._offer(session, [])
        exception = bool(session.exception) and session.destination == "store_credit"
        result = run_tool(
            "write",
            "start_return",
            lambda: self._store.start_return(
                session.customer_id,
                session.order_id or "",
                session.destination or "",
                today,
                now,
                reason=session.reason,
                reason_kind=session.reason_kind,
                sentiment=session.sentiment,
                exception=exception,
            ),
        )
        wrote = ToolTrace(
            name="start_return",
            summary=_write_summary(result),
            payload=result,
        )
        if result.get("status") != "completed" or not result.get("receiptId"):
            return Turn(
                template=not_completed(),
                instruction="The write did not complete. Say that there is no receipt. Do not invent one.",
                tools=[wrote],
                step="Step: receipt",
            )
        session.phase = "done"
        session.return_id = result.get("returnId")
        if result.get("exception"):
            return Turn(
                template=exception_completed(result),
                instruction=(
                    "The write returned status completed as store credit. "
                    "Confirm the store credit, the amount, and the receipt id from the JSON. "
                    "Say the receipt and the parcel label are ready. "
                    "Do not say the Visa was refunded. "
                    "Do not name a carrier that is not in the JSON. "
                    "Do not invent a download address. "
                    "Then ask if they need anything else."
                ),
                tools=[wrote],
                required=[result["receiptId"], result["title"], result["amount"], "store credit"],
                step="Step: receipt and label",
            )
        required = [result["receiptId"], result["title"], result["amount"]]
        if result.get("last4"):
            required.append(str(result["last4"]))
        return Turn(
            template=completed(result),
            instruction=(
                "The write returned status completed. Say the return is complete. "
                "Copy the receipt id, amount, title, and last4 from the JSON. "
                "Do not invent a download address. "
                "Then ask if they need anything else."
            ),
            tools=[wrote],
            required=required,
            step="Step: receipt",
        )

    def _remember_exception(self, session: Session, detail: dict) -> None:
        session.exception = True
        session.order_id = detail["orderId"]
        session.title = detail["title"]
        genre = str(detail.get("genre") or "").strip().lower()
        session.genre = genre or None
        session.phase = "exception_why"
        session.destination = None

    def _reask_exception(self, session: Session, today: date) -> Turn:
        detail = run_tool(
            session.phase,
            "get_order",
            lambda: self._store.get_order(session.customer_id, session.order_id or "", today),
        )
        if detail is None or not session.title or not session.order_id:
            return Turn(
                template=missing_order(),
                instruction="The order is not on this account. Say so. Do not invent an order.",
                step="Step: what happened",
            )
        payload = {
            "orderId": detail["orderId"],
            "title": detail["title"],
            "storeCreditOnly": True,
            "cardOffered": False,
        }
        shown = {"title": detail["title"], "orderId": detail["orderId"]}
        return Turn(
            template=ask_what_happened(shown),
            instruction=(
                "Stay on this order. Ask what happened with it. "
                "Do not list other books. Do not offer store credit or the card."
            ),
            tools=[
                ToolTrace(
                    name="get_order",
                    summary=f"Opened {detail['orderId']}.",
                    payload=payload,
                )
            ],
            required=[detail["title"], detail["orderId"]],
            step="Step: what happened",
        )

    def _ask_why(self, session: Session, detail: dict, tools: list[ToolTrace]) -> Turn:
        session.exception = False
        session.order_id = detail["orderId"]
        session.title = detail["title"]
        genre = str(detail.get("genre") or "").strip().lower()
        session.genre = genre or None
        session.phase = "ask_reason"
        return Turn(
            template=ask_reason({"title": detail["title"], "orderId": detail["orderId"]}),
            instruction=(
                "Ask why they want to return this book. "
                "Do not offer a refund yet. Do not recommend a book. "
                "Do not mention a percent or a discount code. "
                "Do not say a return has started."
            ),
            tools=tools,
            required=[detail["title"], detail["orderId"]],
            step="Step: why it's coming back",
        )

    def _too_late(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        del now
        orders, listed = self._listed(session)
        chosen = named_orders(message, orders)
        if len(chosen) == 1:
            return self._open_window(session, chosen[0], today, listed)
        return self._window_list(session, orders, today, listed)

    def _which_book(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        del now
        if is_password_reset(message):
            return Turn(
                template=password_refused(),
                instruction="Say, in English, that this desk can help with a return and cannot reset a password.",
                intent="out_of_scope",
                step="Step: which book",
            )
        orders, listed = self._listed(session)
        delivered = [order for order in orders if _is_delivered(order)]
        chosen = named_orders(message, orders)
        if len(chosen) == 1:
            return self._open_window(session, chosen[0], today, listed)
        if len(delivered) == 1 and confirms_shown_order(message):
            return self._open_window(session, delivered[0], today, listed)
        return self._window_list(session, orders, today, listed)

    def _exception_why(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        del today
        if is_password_reset(message):
            return Turn(
                template=password_refused(),
                instruction="Say, in English, that this desk can help with a return and cannot reset a password.",
                intent="out_of_scope",
                step="Step: what happened",
            )
        if session.order_id is None or not session.title:
            session.phase = "which_book"
            return self._which_book(session, message, now.date(), now)
        if wants_return_in_play(message):
            if isinstance(session.reason, str) and session.reason.strip():
                session.phase = "exception_offer"
                return self._offer_exception(session)
            return self._reask_exception(session, now.date())
        session.reason = message.strip()
        session.reason_kind = classify_reason(session.reason)
        session.sentiment = label_sentiment(session.reason)
        session.phase = "exception_offer"
        return self._offer_exception(session)

    def _exception_offer(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        if accepts_store_credit_exception(message):
            session.destination = "store_credit"
            session.exception = True
            session.phase = "write"
            return self._write(session, today, now)
        if hedges_store_credit_exception(message):
            return self._confirm_exception(session)
        return self._offer_exception(session)

    def _offer_exception(self, session: Session) -> Turn:
        return self._exception_turn(session, confirm=False)

    def _confirm_exception(self, session: Session) -> Turn:
        return self._exception_turn(session, confirm=True)

    def _exception_turn(self, session: Session, *, confirm: bool) -> Turn:
        if session.order_id is None:
            raise RuntimeError("an exception offer requires an order")
        options = run_tool(
            session.phase,
            "get_refund_options",
            lambda: self._store.get_refund_options(session.customer_id, session.order_id or ""),
        )
        if options is None:
            session.phase = "which_book"
            session.order_id = None
            return Turn(
                template=missing_order(),
                instruction="The order is not on this account. Say so.",
                step="Step: which book",
            )
        payload = {
            "orderId": options["orderId"],
            "title": options["title"],
            "amount": options["amount"],
            "refundableCents": options["refundableCents"],
            "destination": "store_credit",
            "refund": "store credit",
            "exception": True,
            "storeCreditOnly": True,
            "cardOffered": False,
        }
        if confirm:
            return Turn(
                template=exception_confirm(payload),
                instruction=(
                    "They did not clearly accept or refuse the store credit. "
                    "Ask one confirming question, in a clerk's voice, whether they are good "
                    "with the one-time store credit. Copy the amount, the title, and the order id "
                    "from the JSON. Do not repeat the earlier offer. Do not say a return is complete. "
                    "Do not offer the Visa, the card, or original payment."
                ),
                tools=[
                    ToolTrace(
                        name="get_refund_options",
                        summary=f"Confirm store credit for {payload['orderId']}.",
                        payload=payload,
                    )
                ],
                required=[
                    payload["title"],
                    payload["amount"],
                    payload["orderId"],
                    "store credit",
                    "confirm",
                ],
                step="Step: confirm store credit",
            )
        return Turn(
            template=exception_offer(payload),
            instruction=(
                "Offer only a one-time store-credit exception for the amount in the JSON. "
                "Ask if that is acceptable. Do not offer the card, the Visa, or original payment."
            ),
            tools=[
                ToolTrace(
                    name="get_refund_options",
                    summary=f"Store credit exception for {payload['orderId']}.",
                    payload=payload,
                )
            ],
            required=[payload["title"], payload["amount"], "store credit"],
            step="Step: store credit exception",
        )

    def _ask_to_choose(
        self,
        listed: ToolTrace,
        orders: list[dict],
        today: date,
        template: str,
        instruction: str,
    ) -> Turn:
        """Ask which order, with one choice per order taken from the tool payload."""

        marked = [_marked_order(order, today, self._store.return_window_days()) for order in orders]
        listed.payload = {"orders": marked}
        listed.summary = f"Listed {len(marked)} orders to choose from."
        return Turn(
            template=template,
            instruction=instruction,
            tools=[listed],
            choices=_choice_list(marked),
        )

    def _listed(self, session: Session) -> tuple[list[dict], ToolTrace]:
        orders = run_tool(
            session.phase,
            "list_recent_orders",
            lambda: self._store.list_recent_orders(session.customer_id),
        )
        listed = ToolTrace(
            name="list_recent_orders",
            summary=f"Listed {len(orders)} recent orders.",
            payload={"orders": [_public_order(order) for order in orders]},
        )
        return orders, listed

    def _window_list(
        self,
        session: Session,
        orders: list[dict],
        today: date,
        listed: ToolTrace,
    ) -> Turn:
        days = self._store.return_window_days()
        marked = [_marked_order(order, today, days) for order in orders]
        listed.payload = {"orders": marked}
        listed.summary = f"Listed {len(marked)} recent orders with a delivery or trip mark."
        session.phase = "which_book"
        session.exception = False
        required: list[str] = []
        for order in marked:
            required.append(order["title"])
            required.append(order["orderId"])
            mark = order.get("mark")
            if isinstance(mark, str) and mark.strip():
                required.append(mark.strip())
            label = order.get("deliveredLabel")
            if isinstance(label, str) and label.strip():
                required.append(label.strip())
        return Turn(
            template=delivered_window_list(marked),
            instruction=(
                "They asked if it is too late and did not name a book. "
                "Name every recent order. Copy each mark from the JSON. "
                "A delivered book is inside the window or past it. "
                "A book still on the way keeps its stored trip status: "
                "packing, shipped, on the way, or out for delivery. "
                "Do not invent a status or a title. "
                "Do not recite a stored reason. Do not say a return has started. "
                "Ask which book."
            ),
            tools=[listed],
            required=required,
            step="Step: which book",
            choices=_choice_list(marked),
        )

    def _open_window(self, session: Session, selected: dict, today: date, listed: ToolTrace) -> Turn:
        detail = run_tool(
            session.phase,
            "get_order",
            lambda: self._store.get_order(session.customer_id, selected["orderId"], today),
        )
        if detail is None:
            return Turn(
                template=missing_order(),
                instruction="The order is not on this account. Say so. Do not invent an order.",
                tools=[listed],
                step="Step: which book",
            )
        opened = ToolTrace(
            name="get_order",
            summary=f"Opened {detail['orderId']}.",
            payload=_public_order(detail)
            | {
                "eligible": detail["eligible"],
                "returnWindowDays": detail["returnWindowDays"],
                "policy": detail["policy"],
            },
        )
        if not _is_delivered(detail):
            session.phase = "which_book"
            status = detail.get("status")
            required = [detail["title"], detail["orderId"]]
            if isinstance(status, str) and status.strip():
                required.append(status.strip())
            opened.payload.pop("policy", None)
            return Turn(
                template=still_sending(detail),
                instruction=(
                    "This order has not been delivered. Repeat the stored status from the JSON. "
                    "Do not start a return. Do not say it is past the return window."
                ),
                tools=[opened],
                required=required,
                step="Step: which book",
            )
        if detail["eligible"]:
            return self._ask_why(session, detail, [listed, opened])
        label = ""
        delivered = detail.get("deliveredAt")
        if isinstance(delivered, datetime):
            label = spoken_date(delivered)
            opened.payload["deliveredOn"] = iso_day(delivered)
            opened.payload["deliveredLabel"] = label
        elif isinstance(detail.get("deliveredAt"), str):
            opened.payload["deliveredOn"] = str(detail["deliveredAt"])[:10]
        opened.payload["window"] = "past"
        opened.payload["cardBrand"] = "Visa"
        opened.payload["storeCreditOnly"] = True
        self._remember_exception(session, detail)
        shown = {
            "title": detail["title"],
            "orderId": detail["orderId"],
            "returnWindowDays": detail["returnWindowDays"],
            "deliveredLabel": label,
        }
        required = [detail["title"], detail["orderId"], str(detail["returnWindowDays"])]
        if label:
            required.append(label)
        return Turn(
            template=past_window_why(shown),
            instruction=(
                "Say yes, this book is past the 30-day window, so it cannot go back on the Visa. "
                "Ask what happened with it. Do not offer store credit, a card refund, or any amount yet."
            ),
            tools=[listed, opened],
            required=required,
            step="Step: what happened",
        )


def _status_facts(order: dict) -> dict:
    """The stored status fields a status reply is allowed to use.

    Eligibility and the return policy stay off this payload so a draft cannot
    borrow the word "delivered" from the policy text.
    """

    facts = {
        "orderId": order["orderId"],
        "title": order["title"],
        "status": order.get("status"),
    }
    detail = order.get("statusDetail")
    if isinstance(detail, str) and detail.strip():
        facts["statusDetail"] = detail.strip()
    return facts


def _status_required(orders: list[dict]) -> list[str]:
    required: list[str] = []
    for order in orders:
        required.append(str(order["orderId"]))
        required.append(str(order["title"]))
        status = order.get("status")
        if isinstance(status, str) and status.strip():
            required.append(status.strip())
        detail = order.get("statusDetail")
        if isinstance(detail, str) and detail.strip():
            required.append(detail.strip())
    return required


def _is_delivered(order: dict) -> bool:
    status = order.get("status")
    if not isinstance(status, str) or status.strip().casefold() != "delivered":
        return False
    return isinstance(order.get("deliveredAt"), datetime)


def _marked_order(order: dict, today: date, days: int) -> dict:
    """Plain-language group from deliveredAt, the policy window, and status."""

    public = _public_order(order)
    public["returnWindowDays"] = days
    status = order.get("status")
    label = status.strip() if isinstance(status, str) else ""
    delivered = order.get("deliveredAt")
    if isinstance(delivered, datetime) and label.casefold() == "delivered":
        inside = is_eligible(delivered, today, days)
        public["deliveredOn"] = iso_day(delivered)
        public["deliveredLabel"] = spoken_date(delivered)
        public["window"] = "inside" if inside else "past"
        place = "inside" if inside else "past"
        public["mark"] = f"Delivered and {place} the {days}-day window"
        return public
    if is_in_progress(order) and label:
        public["mark"] = f"Still on the way, {label}"
        return public
    public["mark"] = label or "Still on the way"
    return public


def _public_order(order: dict) -> dict:
    return {
        "orderId": order["orderId"],
        "title": order["title"],
        "placedAt": _iso(order.get("placedAt")),
        "deliveredAt": _iso(order.get("deliveredAt")),
        "status": order.get("status"),
    }


def _iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _choice_payload(choice: OrderChoice) -> dict:
    return {"orderId": choice.order_id, "title": choice.title, "mark": choice.mark}


def _choice_list(orders: list[dict]) -> list[OrderChoice]:
    """Order id, title, and mark already stored on these payload rows."""

    choices: list[OrderChoice] = []
    for order in orders:
        order_id = order.get("orderId")
        title = order.get("title")
        mark = order.get("mark")
        if not isinstance(order_id, str) or not order_id.strip():
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        if not isinstance(mark, str) or not mark.strip():
            continue
        choices.append(
            OrderChoice(order_id=order_id.strip(), title=title.strip(), mark=mark.strip())
        )
    return choices


def _is_week_ask(message: str) -> bool:
    from bookly_support.agent.resolve import mentions_week

    return mentions_week(message)


def _about_subject(store: ReturnStore, session: Session, message: str) -> str | None:
    """The title to look up. A named catalog title wins, then any other named title.

    A title they named that is not stocked is still returned, so the reply can
    say it is not on file. With no title in the question, use the book in play.
    """

    named = store.match_catalog_title(message)
    if isinstance(named, str) and named.strip():
        return named.strip()
    phrase = asked_title(message)
    if phrase:
        return phrase
    return _book_in_play(session)


def _book_in_play(session: Session) -> str | None:
    """The recommended title after one was offered, otherwise the order title."""

    recommended = session.recommended_title
    if isinstance(recommended, str) and recommended.strip():
        return recommended.strip()
    title = session.title
    if isinstance(title, str) and title.strip():
        return title.strip()
    return None


def _remember_recommendation(session: Session, recommendation: dict) -> None:
    title = recommendation.get("title")
    if isinstance(title, str) and title.strip():
        session.recommended_title = title.strip()


def _offer_step(session: Session, traces: list[ToolTrace]) -> str:
    """The offer on this turn. The refund question stays in the reply, not this line."""

    if any(tool.name == "issue_goodwill_discount" and tool.payload.get("code") for tool in traces):
        return "Step: 20% on the next purchase"
    if session.genre == "horror" and any(
        tool.name == "recommend_book" and tool.payload.get("title") for tool in traces
    ):
        return "Step: offer a non-horror title"
    return "Step: empathy only"


def _tone_clause(sentiment: str | None) -> str:
    if sentiment == "negative":
        return "Sound especially sorry."
    if sentiment == "positive":
        return "Thank them for explaining, then stay sorry."
    return "Keep the apology plain."


def _write_summary(result: dict) -> str:
    if result.get("status") == "completed" and result.get("receiptId"):
        return f"Completed return {result['receiptId']}."
    return "The return did not complete."
