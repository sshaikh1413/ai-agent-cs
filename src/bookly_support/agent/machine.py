"""Return conversation. The machine picks the tool. Claude does not."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from bookly_support.agent.allowlist import run_tool
from bookly_support.agent.reasons import classify_reason
from bookly_support.agent.resolve import (
    asked_title,
    asks_for_recommendation,
    asks_order_status,
    book_question,
    destination_choice,
    is_decline,
    is_password_reset,
    resolve_order,
    resolve_status,
)
from bookly_support.agent.sentiment import label_sentiment
from bookly_support.agent.templates import (
    about_book,
    ask_anything_else,
    ask_reason,
    closed,
    completed,
    empathy_horror,
    empathy_horror_plain,
    empathy_late,
    empathy_other,
    late_apology,
    list_orders,
    missing_order,
    no_order_in_progress,
    not_completed,
    order_status,
    order_status_choices,
    outside_window,
    password_refused,
    recommend_reply,
    refund_choice,
    week_ambiguous,
    week_none,
)


class ReturnStore(Protocol):
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


@dataclass
class Turn:
    template: str
    instruction: str
    tools: list[ToolTrace] = field(default_factory=list)
    intent: str = "return_refund"
    required: list[str] = field(default_factory=list)
    step: str = "Step: which order"
    customer_reason: str | None = None

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
        return self._identify(session, message, today, now)

    def _done(self, session: Session, message: str, now: datetime) -> Turn:
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
        del now
        if is_password_reset(message):
            return Turn(
                template=password_refused(),
                instruction="Say, in English, that this desk can help with a return and cannot reset a password.",
                intent="out_of_scope",
            )

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
            return Turn(
                template=week_none(listed.payload["orders"]),
                instruction="No order was placed about a week ago. Ask them to pick from the listed orders. Do not say a return has started.",
                tools=[listed],
                required=_titles(listed.payload["orders"]),
            )
        if kind == "ambiguous":
            public = [_public_order(order) for order in matches]
            return Turn(
                template=week_ambiguous(public) if _is_week_ask(message) else list_orders(public),
                instruction="More than one order matches. Ask which one they want. Do not say a return has started.",
                tools=[listed],
                required=_titles(public),
            )
        if kind != "selected":
            return Turn(
                template=list_orders(listed.payload["orders"]),
                instruction="They want to return a product. Name every listed title and order id and ask which one. Do not say a return has started.",
                tools=[listed],
                required=_titles(listed.payload["orders"]),
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
            return Turn(
                template=outside_window(opened.payload),
                instruction="The order is outside the return window. Say so and cite the policy. Do not offer a refund.",
                tools=[listed, opened],
                required=[detail["title"], detail["orderId"]],
            )

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
            tools=[listed, opened],
            required=[detail["title"], detail["orderId"]],
            step="Step: why it's coming back",
        )

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
                        payload={"orders": public},
                    )
                ],
                intent="order_status",
                required=_status_required(public),
                step="Step: order status",
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


def _titles(orders: list[dict]) -> list[str]:
    return [order["title"] for order in orders if order.get("title")]


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
