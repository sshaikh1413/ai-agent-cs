"""Return conversation. The machine picks the tool. Claude does not."""

from __future__ import annotations

import re

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol

from bookly_support.agent.allowlist import run_tool
from bookly_support.agent.articles import (
    FAQ,
    FAQ_CHOICE_PREFIX,
    FAQ_MORE_PREFIX,
    FAQ_PAGE_SIZE,
    article_named,
    faq_page,
    faq_pick,
    normalize_article,
)
from bookly_support.agent.reasons import classify_reason, reason_topic
from bookly_support.agent.eligibility import is_eligible
from bookly_support.agent.resolve import (
    asked_title,
    agrees_to_read,
    asks_for_agent,
    confirms_shown_order,
    is_decline,
    is_in_progress,
    not_this_book,
    named_orders,
    partial_title_matches,
    resolve_order,
    resolve_status,
    wants_full_list,
)
from bookly_support.agent.window import as_utc, days_past_window, iso_day, short_date, spoken_date
from bookly_support.agent.understand import (
    RuleUnderstander,
    TurnContext,
    Understander,
    Understanding,
    offer_for,
    validate,
)
from bookly_support.agent.templates import (
    about_book,
    ask_anything_else,
    ask_match_details,
    ask_match_price,
    ask_match_store,
    ask_title_again,
    purchase_cancelled,
    purchase_offer,
    purchase_placed,
    purchase_unavailable,
    purchase_which,
    ask_title_or_date,
    ask_reason,
    ask_what_happened,
    closed,
    completed,
    completed_in_transit,
    empathy_horror,
    empathy_horror_plain,
    empathy_late,
    empathy_other,
    delivered_window_list,
    exception_card,
    exception_completed,
    exception_confirm,
    exception_offer,
    faq_list,
    handoff,
    in_transit_why,
    in_transit_lead,
    in_transit_status,
    late_apology,
    list_orders,
    missing_order,
    no_order_in_progress,
    no_parcel_label,
    not_completed,
    parcel_label_ready,
    customer_discounts,
    order_status,
    order_status_choices,
    could_not_find,
    ordered_none,
    ordered_none_offer,
    ordered_several,
    past_window,
    price_match_offer,
    price_match_reask,
    price_matched,
    price_not_lower,
    wrong_book,
    recommend_reply,
    refund_choice,
    still_sending,
    week_ambiguous,
    week_none,
    which_topic,
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

    def policy_articles(self) -> list[dict]:
        """Shop articles, with the example questions used to match one."""

    def get_policy_article(self, article_id: str) -> dict | None:
        """One article. The return-window day count comes from the existing policy."""

    def list_customer_discounts(self, customer_id: str) -> dict:
        """Discount codes stored for this customer."""

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

    def issue_parcel_label(
        self,
        customer_id: str,
        return_id: str | None = None,
        order_id: str | None = None,
    ) -> dict:
        """The parcel label for a completed return, or status none when there isn't one."""


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
    # Mara already asked for the title or the order date, so the next miss lists the orders.
    asked_which: bool = False
    # On a call, Mara offered to read the recent orders. A yes reads them.
    offered_list: bool = False
    # A lower price found elsewhere, gathered over the price-match turns.
    match_price_cents: int | None = None
    match_store: str | None = None
    # A book being ordered: its title, a corrected address for this order only, and the key
    # that makes a repeated yes return the same order.
    purchase_title: str | None = None
    purchase_address: str | None = None
    purchase_key: str | None = None
    # This turn came from a voice call: the list is offered, not read unprompted. Not stored.
    voice: bool = field(default=False, repr=False, compare=False)
    # This turn's book was worked out from a description, part of a title, or a date rather
    # than its exact title or order id, so Mara says she found it. Not stored.
    found_by_search: bool = field(default=False, repr=False, compare=False)
    # This turn's validated label. Not stored with the session.
    understanding: Understanding | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class OrderChoice:
    """One book the customer can click. Copied from the tool payload."""

    order_id: str
    title: str
    mark: str
    # When it was ordered, as Mara says it. The call reads this instead of the order id.
    placed: str | None = None


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
    # False when the question already asks for the title or a date: the call does not read
    # the list aloud yet. The chat still shows the buttons.
    read_choices: bool = True

    @property
    def payload(self) -> dict:
        """Tool facts for phrasing. A late delivery also includes the reason they typed."""

        body: dict = {"results": [tool.payload for tool in self.tools]}
        if isinstance(self.customer_reason, str):
            body["reason"] = self.customer_reason.strip()
        return body


# The understander used when none is passed in. The pure tests replace it.
DEFAULT_UNDERSTANDER: Understander = RuleUnderstander()


class Machine:
    """The validator. Claude labels the message; this code decides what may run."""

    def __init__(self, store: ReturnStore, understander: Understander | None = None) -> None:
        self._store = store
        self._understander = understander

    def step(
        self, session: Session, message: str, *, today: date, now: datetime, voice: bool = False
    ) -> Turn:
        session.voice = voice
        if session.phase == "write":
            return self._write(session, today, now)
        if asks_for_agent(message):
            return self._handoff(session)
        if session.phase not in {"empathy", "closed"}:
            faq = self._faq_turn(session, message)
            if faq is not None:
                return faq
        session.understanding = self._understand(session, message, today)
        if _has(session, "human_agent"):
            return self._handoff(session)
        if _has(session, "buy_book") and self._purchase_can_start(session):
            return self._start_purchase(session, message)
        if _has(session, "parcel_label"):
            return self._parcel_label(session)
        kind = _about_kind(session)
        subject = _about_subject(self._store, session, message) if kind else None
        if kind and subject and session.phase != "closed":
            return self._about(session, subject, kind)
        if session.phase not in {"write", "empathy", "closed"} and self._is_status_question(
            session, message
        ):
            return self._status(session, message, today)
        if session.phase == "done":
            return self._done(session, message, now)
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
        if session.phase == "purchase_which":
            return self._start_purchase(session, message)
        if session.phase == "purchase_confirm":
            return self._purchase_confirm(session, message, now)
        if session.phase == "price_match_offer":
            return self._price_match_offer(session, message, today, now)
        if session.phase == "price_match_details":
            return self._price_match_details(session, message, today, now)
        return self._identify(session, message, today, now)

    def _understand(self, session: Session, message: str, today: date | None = None) -> Understanding:
        """One label for this turn, checked against what this step allows."""

        context = self._context(session, today)
        understander = self._understander or DEFAULT_UNDERSTANDER
        return validate(understander.understand(message, context), context)

    def _context(self, session: Session, today: date | None = None) -> TurnContext:
        reader = getattr(self._store, "policy_articles", None)
        articles = [normalize_article(article) for article in (reader() if reader else [])]
        orders = self._store.list_recent_orders(session.customer_id)
        return TurnContext(
            phase=session.phase,
            offer=offer_for(session.phase, session.exception),
            exception_open=session.exception,
            articles=tuple((item["id"], item["topic"]) for item in articles),
            orders=tuple(
                (str(order.get("orderId")), str(order.get("title") or ""))
                for order in orders
                if order.get("orderId")
            ),
            book_in_play=_book_in_play(session),
            today=today,
        )

    def _done(self, session: Session, message: str, now: datetime) -> Turn:
        if _has(session, "return_item"):
            return self._return_again(session, message, now)
        if session.exception and _offer_reply(session) == "accept":
            session.destination = "store_credit"
            session.phase = "write"
            return self._write(session, now.date(), now)
        if _has(session, "goodbye"):
            session.phase = "closed"
            session.closed_at = now
            return Turn(
                template=closed(),
                instruction="They are done. Close the chat in one short English sentence. Do not mention orders, money, dates, or cards.",
                intent="clarify",
                step="Step: close",
            )
        if _has(session, "recommend"):
            return self._recommend(session)
        if _has(session, "password_reset"):
            return self._sign_in(session)
        if _has(session, "own_discount"):
            return self._own_discount(session)
        policy = self._policy_turn(session, message)
        if policy is not None:
            return policy
        return Turn(
            template=ask_anything_else(),
            instruction="Ask if they need help with anything else. Do not mention orders, money, dates, or cards.",
            intent="clarify",
            step="Step: anything else",
        )

    def _return_again(self, session: Session, message: str, now: datetime) -> Turn:
        """Start the which-book question again. The stored return stays."""

        session.phase = "identify_order"
        session.order_id = None
        session.destination = None
        session.reason = None
        session.reason_kind = None
        session.sentiment = None
        session.title = None
        session.genre = None
        session.exception = False
        session.asked_which = False
        session.offered_list = False
        session.match_price_cents = None
        session.match_store = None
        return self._identify(session, message, now.date(), now)

    def _parcel_label(self, session: Session) -> Turn:
        """The label for this conversation's completed return, or a line that invents none."""

        return_id = session.return_id if isinstance(session.return_id, str) and session.return_id else None
        order_id = session.order_id if isinstance(session.order_id, str) and session.order_id else None
        if return_id is None and not (session.phase == "done" and order_id is not None):
            return self._no_parcel_label()
        result = run_tool(
            session.phase,
            "issue_parcel_label",
            lambda: self._store.issue_parcel_label(
                session.customer_id,
                return_id=return_id,
                order_id=order_id,
            ),
        )
        if result.get("status") != "ready" or not result.get("labelId") or not result.get("trackingNumber"):
            return self._no_parcel_label()
        required = [
            str(result["trackingNumber"]),
            str(result["carrier"]),
            str(result["title"]),
            str(result["orderId"]),
        ]
        return Turn(
            template=parcel_label_ready(result),
            instruction=(
                "The parcel label for the completed return is ready. "
                "Copy the tracking number, the carrier, the title, and the order id from the JSON. "
                "Say the label is ready to download. "
                "Do not name a carrier that is not in the JSON. "
                "Do not invent a tracking number or a download address. "
                "Do not ask which policy topic they mean."
            ),
            tools=[
                ToolTrace(
                    name="issue_parcel_label",
                    summary=f"Parcel label {result['labelId']} for {result['orderId']}.",
                    payload=result,
                )
            ],
            intent="shipping",
            required=required,
            step="Step: parcel label",
        )

    def _no_parcel_label(self) -> Turn:
        return Turn(
            template=no_parcel_label(),
            instruction=(
                "No return is done in this conversation. "
                "Say there isn't a parcel label yet because no return is done. "
                "Do not invent a tracking number, a carrier, or a label. "
                "Do not list policy topics and do not guess an article."
            ),
            intent="clarify",
            step="Step: parcel label",
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
        if _has(session, "password_reset"):
            return self._sign_in(session)
        if _has(session, "own_discount"):
            return self._own_discount(session)
        policy = self._policy_turn(session, message)
        if policy is not None:
            return policy
        if _has(session, "too_late"):
            return self._too_late(session, message, today, now)

        orders = _without_completed_returns(
            run_tool(
                session.phase,
                "list_recent_orders",
                lambda: self._store.list_recent_orders(session.customer_id),
            )
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
        if kind == "list" and orders:
            pointed = _pointed_order(session, orders) or partial_title_matches(message, orders)
            if len(pointed) == 1:
                kind, matches = "selected", pointed
            elif pointed:
                return self._ask_to_choose(
                    listed,
                    pointed,
                    today,
                    list_orders(pointed),
                    (
                        "More than one order fits what they said. Ask which one, in one short question. "
                        "Do not read the titles or the order ids. Do not say a return has started."
                    ),
                )
        if kind == "list" and orders:
            window = _ordered_window(session)
            if window is not None:
                dated = _placed_between(orders, *window)
                session.asked_which = True
                if len(dated) == 1:
                    kind, matches = "selected", dated
                elif dated:
                    return self._ask_to_choose(
                        listed,
                        dated,
                        today,
                        ordered_several(),
                        (
                            "More than one order was placed around the date they gave. "
                            "Ask which one, in one short question. Do not read the titles or the order ids. "
                            "Do not invent an order. Do not say a return has started."
                        ),
                    )
                elif session.voice:
                    return self._offer_to_read(session, listed, orders, today, ordered_none_offer())
                else:
                    return self._ask_to_choose(
                        listed,
                        orders,
                        today,
                        ordered_none(),
                        (
                            "No order was placed around the date they gave. Say so, then ask which book, "
                            "in one short question. Do not read the titles or the order ids. "
                            "Do not invent an order. Do not say a return has started."
                        ),
                    )
            elif session.offered_list and (agrees_to_read(message) or wants_full_list(message)):
                # They said yes to hearing the list: fall through and read it.
                session.offered_list = False
            elif session.offered_list and is_decline(message):
                session.offered_list = False
                asked = self._ask_to_choose(
                    listed,
                    orders,
                    today,
                    ask_title_again(),
                    (
                        "They do not want the list read. Ask, in one short question, for the title "
                        "or about when they ordered it. Do not read the titles or the order ids."
                    ),
                )
                asked.read_choices = False
                return asked
            elif len(orders) > 1 and not session.asked_which and not wants_full_list(message):
                session.asked_which = True
                asked = self._ask_to_choose(
                    listed,
                    orders,
                    today,
                    ask_title_or_date(),
                    (
                        "They want to return a book but did not say which. Ask, in one short question, "
                        "whether they remember the title or about when they ordered it. "
                        "Do not read the titles or the order ids. Do not say a return has started."
                    ),
                )
                asked.read_choices = False
                return asked
            elif session.voice and len(orders) > 1 and not wants_full_list(message):
                # On a call, a book Mara cannot place gets an offer, not a long list read aloud.
                return self._offer_to_read(session, listed, orders, today, could_not_find())
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
        session.found_by_search = not (named_orders(message, orders) or confirms_shown_order(message))
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
            if not _is_delivered(detail) and is_in_progress(detail):
                return self._start_in_transit(session, detail, opened, [opened], today, now)
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
            return self._past_window(session, detail, opened, [opened], today, now, card="card")

        return self._start_return(session, detail, [listed, opened], today, now)

    def _reason(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        if _has(session, "password_reset"):
            return self._sign_in(session)
        if session.order_id is None or not session.title:
            session.phase = "identify_order"
            return self._identify(session, message, today, now)
        if not_this_book(message):
            return self._wrong_book(session, today)
        session.reason = message.strip()
        session.reason_kind, session.sentiment = _reason_labels(session)
        session.phase = "empathy"
        return self._empathy_and_offer(session, today, now)

    def _empathy_and_offer(self, session: Session, today: date, now: datetime) -> Turn:
        del today
        if session.reason_kind is None and session.reason:
            session.reason_kind = classify_reason(session.reason)
        title = session.title or "this book"
        sentiment = session.sentiment
        traces: list[ToolTrace] = []
        lead = ""
        instruction = ""
        extra_required: list[str] = []
        late = session.reason_kind == "late_delivery"
        if not late and _reason_topic(session) == "cheaper_elsewhere":
            return self._offer_price_match(session)
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
            topic = _reason_topic(session)
            if recommendation.get("title"):
                lead = empathy_horror(title, recommendation, sentiment, topic)
                extra_required = [str(recommendation["title"])]
            else:
                lead = empathy_horror_plain(title, sentiment, topic)
            instruction = (
                f"{_tone_clause(sentiment)} "
                f"Their reason is about: {topic.replace('_', ' ')}. Acknowledge it in your own words, "
                "matching what they said: if it was too scary, say so; if it was not scary enough, say "
                "that. Do not claim the opposite of their reason, and do not quote their sentence. "
                "Recommend only the title in the JSON. "
                "Do not mention a discount, a percent, or a code. "
                "Do not invent a book title."
            )
        else:
            topic = _reason_topic(session)
            lead = empathy_other(title, topic, sentiment)
            instruction = (
                f"{_tone_clause(sentiment)} "
                f"Their reason is about: {topic.replace('_', ' ')}. Acknowledge it warmly in your own "
                "words, the way a bookstore clerk would, in one short sentence. Do not repeat, quote, "
                "or paraphrase their sentence back to them, and do not say 'I hear you'. "
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
        if kind in {"several", "none"}:
            pointed = _pointed_order(session, orders)
            if pointed:
                kind, chosen = "one", pointed
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
        understanding = session.understanding
        choice = understanding.destination if understanding else None
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
        later = (
            " The book has not arrived yet, so say the refund happens once it is back with us."
            if options.get("awaitingDelivery")
            else ""
        )
        return Turn(
            template=refund_choice(options),
            instruction=(
                "Offer the refund destinations in the JSON. Ask them to choose original payment "
                f"or store credit. Do not say the return is complete or that it has started.{later}"
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
        if result.get("awaitingDelivery"):
            required = [result["receiptId"], result["title"], result["amount"], str(result.get("shipBackDays") or 14)]
            if result.get("last4"):
                required.append(str(result["last4"]))
            return Turn(
                template=completed_in_transit(result),
                instruction=(
                    "The return is written, but the book has not arrived yet. Copy the receipt id, "
                    "amount, and title from the JSON. Say: once it arrives, they have the number of days "
                    "in shipBackDays to send it back with the prepaid shipping label, and the refund is "
                    "issued when we receive it. Do not say the "
                    "money has been refunded already. Say the receipt and the shipping label are "
                    "ready. Then ask if they need anything else."
                ),
                tools=[wrote],
                required=required,
                step="Step: receipt and label",
            )
        if result.get("exception"):
            return Turn(
                template=exception_completed(result),
                instruction=(
                    "The write returned status completed as store credit. "
                    "Confirm the store credit, the amount, and the receipt id from the JSON. "
                    "Say the return confirmation receipt and a prepaid shipping label are ready, and that "
                    "they have the number of days in shipBackDays to send the book back with the label. "
                    "Do not say the Visa was refunded. "
                    "Do not name a carrier that is not in the JSON. "
                    "Do not invent a download address. "
                    "Then ask if they need anything else."
                ),
                tools=[wrote],
                required=[result["receiptId"], result["title"], result["amount"], "store credit", str(result.get("shipBackDays") or 14)],
                step="Step: receipt and label",
            )
        required = [result["receiptId"], result["title"], result["amount"], str(result.get("shipBackDays") or 14)]
        if result.get("last4"):
            required.append(str(result["last4"]))
        return Turn(
            template=completed(result),
            instruction=(
                "The write returned status completed. Say the return is complete. "
                "Copy the receipt id, amount, title, and last4 from the JSON. "
                "Say the return confirmation receipt and a prepaid shipping label are ready, and that "
                "they have the number of days in shipBackDays to send the book back with the label. "
                "Do not name a carrier that is not in the JSON. Do not invent a download address. "
                "Then ask if they need anything else."
            ),
            tools=[wrote],
            required=required,
            step="Step: receipt and label",
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
                "Stay on this order. Ask what the reason for the return is. "
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

    def _wrong_book(self, session: Session, today: date) -> Turn:
        """They said no right after Mara named the book: drop it and ask which one."""

        session.phase = "identify_order"
        session.order_id = None
        session.title = None
        session.genre = None
        session.asked_which = True
        orders, listed = self._listed(session)
        turn = self._ask_to_choose(
            listed,
            orders,
            today,
            wrong_book(),
            (
                "Mara named the wrong book. Apologize briefly and ask for the title or about when "
                "they ordered it, in one short question. Do not read the titles or the order ids."
            ),
        )
        turn.read_choices = False
        return turn

    def _offer_to_read(
        self, session: Session, listed: ToolTrace, orders: list[dict], today: date, template: str
    ) -> Turn:
        """On a call: say the book was not found and offer to read the recent orders."""

        session.offered_list = True
        offer = self._ask_to_choose(
            listed,
            orders,
            today,
            template,
            (
                "On a phone call, the book they described was not found. Say so, then offer to read "
                "their recent orders, in one short question. Do not read the titles or the order ids. "
                "Do not invent an order. Do not say a return has started."
            ),
        )
        offer.read_choices = False
        return offer

    def _start_return(
        self, session: Session, detail: dict, tools: list[ToolTrace], today: date, now: datetime
    ) -> Turn:
        """Ask why, unless they already said why in the same sentence. Then go straight on."""

        asked = self._ask_why(session, detail, tools)
        reason = _stated_reason(session)
        if reason is None:
            return asked
        session.reason = reason
        session.reason_kind, session.sentiment = _reason_labels(session)
        session.phase = "empathy"
        return self._empathy_and_offer(session, today, now)

    def _purchase_can_start(self, session: Session) -> bool:
        """Between tasks, any request to buy starts an order. In the middle of a return, only one
        that names a book does, so "I'll take it" or "yes" stays with the return."""

        if session.phase in {"empathy", "closed", "purchase_confirm", "write"}:
            return False
        if session.phase in {"identify_order", "done", "which_book", "purchase_which"}:
            return True
        understanding = session.understanding
        return bool(understanding and understanding.wanted_title)

    def _start_purchase(self, session: Session, message: str) -> Turn:
        """They want to buy a book: work out which one, then confirm price, card, and address."""

        title = self._purchase_title(session, message)
        if title is None:
            session.phase = "purchase_which"
            return Turn(
                template=purchase_which(),
                instruction="They want to order a book but did not say which. Ask which one, in one short question.",
                intent="clarify",
                step="Step: which book to order",
            )
        offer = run_tool(session.phase, "get_book_offer", lambda: self._store.get_book_offer(session.customer_id, title))
        if offer is None or not offer.get("cardAvailable") or not offer.get("address"):
            session.phase = "done"
            return Turn(
                template=purchase_unavailable(title),
                instruction="Say you can't order this book right now. Do not invent a price, a card, or an address.",
                step="Step: anything else",
            )
        session.purchase_title = offer["title"]
        session.purchase_address = None
        session.purchase_key = f"{session.id}:{offer['title']}"
        session.phase = "purchase_confirm"
        return self._purchase_offer_turn(offer, new_address=False)

    def _purchase_offer_turn(self, offer: dict, *, new_address: bool) -> Turn:
        return Turn(
            template=purchase_offer(offer, new_address=new_address),
            instruction=(
                "They want to order this book. "
                + ("Say you'll send it to the new address in the JSON instead. " if new_address else "Start with a warm yes. ")
                + "Confirm the title and author, the price, free 2-day delivery, the total on the card in the "
                "JSON, and the address, copied from the JSON. Ask if that looks right before you order. "
                "Do not say the order is placed."
            ),
            tools=[ToolTrace(name="get_book_offer", summary=f"Offer for {offer['title']}.", payload=offer)],
            required=[offer["title"], offer["total"], str(offer.get("last4") or "")],
            step="Step: confirm the order",
        )

    def _purchase_confirm(self, session: Session, message: str, now: datetime) -> Turn:
        understanding = session.understanding
        title = session.purchase_title or ""
        new_address = understanding.ship_to if understanding else None
        if new_address and re.search(r"\d", new_address):
            session.purchase_address = new_address
            offer = run_tool(
                session.phase,
                "get_book_offer",
                lambda: self._store.get_book_offer(session.customer_id, title, new_address),
            )
            if offer is not None:
                return self._purchase_offer_turn(offer, new_address=True)
        if _has(session, "buy_book"):
            wanted = self._purchase_title(session, message)
            if wanted and wanted != title:
                return self._start_purchase(session, message)
        reply = _offer_reply(session)
        if reply == "accept":
            placed = run_tool(
                session.phase,
                "place_order",
                lambda: self._store.place_order(
                    session.customer_id, title, session.purchase_address, session.purchase_key or f"{session.id}:{title}", now
                ),
            )
            session.phase = "done"
            if placed.get("status") != "placed":
                return Turn(
                    template=purchase_unavailable(title),
                    instruction="The order did not go through. Say so. Do not say it was placed.",
                    tools=[ToolTrace(name="place_order", summary="The order was not placed.", payload=placed)],
                    step="Step: anything else",
                )
            return Turn(
                template=purchase_placed(placed),
                instruction=(
                    "The order is placed. Say so, copying the title, order id, total, card, delivery time, and "
                    "address from the JSON, and that the order confirmation is ready. Then ask if there's anything else."
                ),
                tools=[ToolTrace(name="place_order", summary=f"Placed order {placed['orderId']}.", payload=placed)],
                required=[placed["orderId"], placed["title"], placed["total"], "2 business days"],
                step="Step: order placed",
            )
        if reply == "refuse":
            session.phase = "done"
            return Turn(
                template=purchase_cancelled(),
                instruction="They don't want to order. Say you haven't placed it, and ask if there's anything else.",
                step="Step: anything else",
            )
        offer = run_tool(
            session.phase,
            "get_book_offer",
            lambda: self._store.get_book_offer(session.customer_id, title, session.purchase_address),
        )
        if offer is None:
            session.phase = "done"
            return Turn(template=purchase_unavailable(title), instruction="Say you can't order it right now.", step="Step: anything else")
        return self._purchase_offer_turn(offer, new_address=False)

    def _purchase_title(self, session: Session, message: str) -> str | None:
        """The catalog title they mean: named (even misspelled), or the book Mara just suggested."""

        from difflib import get_close_matches

        understanding = session.understanding
        said = (understanding.wanted_title if understanding else None) or ""
        titles = list(getattr(self._store, "catalog_titles", lambda: [])())
        by_key = {t.casefold(): t for t in titles}
        for text in (said, message):
            if text:
                exact = self._store.match_catalog_title(text)
                if exact:
                    return exact
        if said:
            close = get_close_matches(said.casefold(), list(by_key), n=1, cutoff=0.75)
            if close:
                return by_key[close[0]]
        suggested = session.recommended_title
        if suggested and (not said or get_close_matches(said.casefold(), [suggested.casefold()], n=1, cutoff=0.6)):
            return suggested
        return None

    def _offer_price_match(self, session: Session) -> Turn:
        """Found it cheaper elsewhere: offer to keep the book and refund the difference."""

        _remember_match_details(session)
        session.phase = "price_match_offer"
        return Turn(
            template=price_match_offer(session.title or "this book", session.sentiment),
            instruction=(
                "They found the book for less at another store. That is good news for them, so sound "
                "pleased for them: do not apologize, say sorry, or call it a letdown. Then offer a price "
                "match instead of a return: they keep the book and you refund the difference. Ask if "
                "they'd like that. Do not name an amount or a store yet. Do not offer the card refund "
                "or store credit yet."
            ),
            step="Step: price match offer",
        )

    def _price_match_offer(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        _remember_match_details(session)
        reply = _offer_reply(session)
        if reply == "accept" or (reply is None and session.match_price_cents is not None):
            session.phase = "price_match_details"
            return self._price_match_details(session, message, today, now)
        if reply == "refuse":
            return self._decline_price_match(session)
        return Turn(
            template=price_match_reask(),
            instruction=(
                "They did not clearly say yes or no to the price match. Ask once more, in one short "
                "question: a price match (keep the book, refund the difference) or the return."
            ),
            step="Step: price match offer",
        )

    def _decline_price_match(self, session: Session) -> Turn:
        """No price match: the usual refund question, or the store-credit exception past the window."""

        offer = self._refund_question(session, [])
        offer.template = f"No problem. {offer.template}"
        return offer

    def _refund_question(self, session: Session, prior: list[ToolTrace]) -> Turn:
        """Card or store credit inside the window; past it, only the one-time store credit."""

        if session.exception:
            session.phase = "exception_offer"
            offer = self._offer_exception(session)
            offer.tools = [*prior, *offer.tools]
            return offer
        session.phase = "choose_destination"
        return self._offer(session, prior)

    def _price_match_details(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        """Gather the price and the store, then check that store and refund the difference."""

        del today
        if is_decline(message) or re.search(r"\b(?:never mind|just (?:return|refund))\b", message, re.IGNORECASE):
            return self._decline_price_match(session)
        _remember_match_details(session)
        price, store = session.match_price_cents, session.match_store
        step = "Step: price match"
        if price is None or store is None:
            if price is None and store is None:
                template = ask_match_details()
            elif price is None:
                template = ask_match_price(store or "")
            else:
                template = ask_match_store(price)
            return Turn(
                template=template,
                instruction=(
                    "Ask, in one short question, for what is still missing: the lower price they found, "
                    "the store, or both. Do not name a price or a store they did not say."
                ),
                step=step,
            )
        title = session.title or ""
        checked = run_tool(
            session.phase,
            "check_competitor_price",
            lambda: self._store.check_competitor_price(title, store, price),
        )
        matched = run_tool(
            session.phase,
            "issue_price_match",
            lambda: self._store.issue_price_match(session.customer_id, session.order_id or "", store, price, now),
        )
        traces = [
            ToolTrace(
                name="check_competitor_price",
                summary=f"Checked {store} for {title}.",
                payload=checked,
            ),
            ToolTrace(
                name="issue_price_match",
                summary=(
                    f"Refunded the {matched.get('difference')} difference."
                    if matched.get("status") == "matched"
                    else "Not lower than the price paid."
                ),
                payload=matched,
            ),
        ]
        if matched.get("status") == "matched":
            session.phase = "done"
            # They keep the book: a past-window store-credit offer is no longer open.
            session.exception = False
            required = [matched["title"], matched["store"], matched["price"], matched["difference"]]
            if matched.get("last4"):
                required.append(str(matched["last4"]))
            return Turn(
                template=price_matched(matched),
                instruction=(
                    "The store check found the price, and the price match is done. Say it's great news, "
                    "that you see the book at that store for that price, and that you'll refund the "
                    "difference to the card in the JSON (or as store credit). Copy the store, price, "
                    "difference, and last4 from the JSON. They keep the book; do not mention a return "
                    "or a shipping label. Then ask if there's anything else."
                ),
                tools=traces,
                required=required,
                step=step,
            )
        if matched.get("status") != "not_lower":
            return self._decline_price_match(session)
        offer = self._refund_question(session, traces)
        offer.template = f"{price_not_lower(matched)} {offer.template}"
        offer.instruction = (
            "That price is not lower than what they paid, so it cannot be matched. Say so, copying "
            f"both prices from the JSON. {offer.instruction}"
        )
        offer.required = [matched["price"], matched["paid"], *offer.required]
        return offer

    def _start_in_transit(
        self,
        session: Session,
        detail: dict,
        opened: ToolTrace,
        tools: list[ToolTrace],
        today: date,
        now: datetime,
    ) -> Turn:
        """Not delivered yet: say so, then start the return so they can send it back on arrival."""

        opened.payload.pop("policy", None)
        opened.payload["awaitingDelivery"] = True
        status = str(detail.get("status") or "").strip()
        required = [detail["title"], detail["orderId"], *([status] if status else [])]
        lead = (
            "This book has not been delivered yet. Say so and copy its status from the JSON. "
            "Say you can still start the return now, and they can send it back once it arrives."
        )
        turn = self._start_return(session, detail, tools, today, now)
        if session.phase == "ask_reason":
            return Turn(
                template=in_transit_why(detail),
                instruction=(
                    f"{lead} Then ask why they want to return it. Do not offer a refund yet. "
                    "Do not say a return is complete."
                ),
                tools=tools,
                required=required,
                step="Step: why it's coming back",
            )
        # They already said why. A price match keeps the book, so only the status leads it;
        # otherwise the status and the start-the-return line lead the refund question.
        if session.phase == "price_match_offer":
            turn.template = f"{in_transit_status(detail)} {turn.template}"
            turn.instruction = (
                "This book has not been delivered yet. Say so and copy its status from the JSON. "
                f"{turn.instruction}"
            )
        else:
            turn.template = f"{in_transit_lead(detail)} {turn.template}"
            turn.instruction = f"{lead} {turn.instruction}"
        turn.tools = [*tools, *turn.tools]
        turn.required = [*required, *turn.required]
        return turn

    def _past_window(
        self,
        session: Session,
        detail: dict,
        opened: ToolTrace,
        tools: list[ToolTrace],
        today: date,
        now: datetime,
        *,
        card: str,
    ) -> Turn:
        """Past the window: when it was ordered and delivered, how many days past the window it
        is now, and that it cannot go back on the card. Then what happened, unless they said."""

        del now
        window = detail["returnWindowDays"]
        shown: dict = {"title": detail["title"], "orderId": detail["orderId"], "returnWindowDays": window}
        required = [detail["title"], detail["orderId"], str(window)]
        delivered = detail.get("deliveredAt")
        if isinstance(delivered, datetime):
            shown["deliveredLabel"] = short_date(delivered, today)
            shown["daysPastWindow"] = days_past_window(delivered, today, window)
            opened.payload["deliveredOn"] = iso_day(delivered)
            required.append(shown["deliveredLabel"])
            if shown["daysPastWindow"] > 0:
                required.append(str(shown["daysPastWindow"]))
        elif isinstance(delivered, str):
            opened.payload["deliveredOn"] = delivered[:10]
        placed = detail.get("placedAt")
        if isinstance(placed, datetime):
            shown["placedLabel"] = short_date(placed, today)
            required.append(shown["placedLabel"])
        opened.payload.update({key: value for key, value in shown.items() if key not in {"title", "orderId"}})
        opened.payload["window"] = "past"
        opened.payload["storeCreditOnly"] = True
        opened.payload["cardOffered"] = False
        if card == "Visa":
            opened.payload["cardBrand"] = "Visa"
        self._remember_exception(session, detail)
        facts = (
            "Say when they ordered it and when it was delivered, how many days past the return "
            f"window it is now, and that it cannot go back on the {card}. Copy the dates and the "
            "numbers from the JSON. Stay on this order. Do not list other orders."
        )
        reason = _stated_reason(session)
        if reason is None:
            return Turn(
                template=past_window(shown, card=card),
                instruction=(
                    f"{facts} Ask what the reason for the return is. "
                    "Do not offer store credit, a card refund, or any amount yet."
                ),
                tools=tools,
                required=required,
                step="Step: what happened",
            )
        session.reason = reason
        session.reason_kind, session.sentiment = _reason_labels(session)
        if _reason_topic(session) == "cheaper_elsewhere":
            offer = self._offer_price_match(session)
            return Turn(
                template=f"{past_window(shown, card=card, ask=False)} {offer.template}",
                instruction=f"{facts} They already said what happened, so do not ask. {offer.instruction}",
                tools=tools,
                required=required,
                step=offer.step,
            )
        session.phase = "exception_offer"
        offer = self._offer_exception(session)
        return Turn(
            template=f"{past_window(shown, card=card, ask=False)} {offer.template}",
            instruction=(
                f"{facts} They already said what happened, so do not ask. "
                "Then offer only the one-time store-credit exception for the amount in the JSON "
                "and ask if that is acceptable. Do not offer the card, the Visa, or original payment."
            ),
            tools=tools + offer.tools,
            required=required + offer.required,
            step=offer.step,
        )

    def _handoff(self, session: Session) -> Turn:
        """They asked for a person. The step stays, so nothing in progress is lost."""

        session.understanding = None
        return Turn(
            template=handoff(),
            instruction=(
                "They asked for a person. In one short sentence, say one moment please, and that "
                "you'll connect them with one of our agents. Do not mention orders, money, dates, "
                "or cards. Do not promise a wait time."
            ),
            intent="handoff",
            step="Step: connect to an agent",
        )

    def _ask_why(self, session: Session, detail: dict, tools: list[ToolTrace]) -> Turn:
        session.exception = False
        session.order_id = detail["orderId"]
        session.title = detail["title"]
        genre = str(detail.get("genre") or "").strip().lower()
        session.genre = genre or None
        session.phase = "ask_reason"
        found = session.found_by_search
        return Turn(
            template=ask_reason({"title": detail["title"], "orderId": detail["orderId"]}, found=found),
            instruction=(
                (
                    "They described the book instead of naming it, and you worked out which one. "
                    "Open by saying you found it (for example, \"Found it!\"), not \"Sure\". "
                    if found
                    else ""
                )
                + "Ask why they want to return this book. "
                "Do not offer a refund yet. Do not recommend a book. "
                "Do not mention a percent or a discount code. "
                "Do not say a return has started."
            ),
            tools=tools,
            required=[detail["title"], detail["orderId"]],
            step="Step: why it's coming back",
        )

    def _is_status_question(self, session: Session, message: str) -> bool:
        """Order status, including 'where is The Night Circus?'."""

        del message
        return _has(session, "order_status")

    def _sign_in(self, session: Session) -> Turn:
        """The sign-in article. This desk does not send a code or confirm an account."""

        return self._article_turn(session, "sign-in")

    def _own_discount(self, session: Session) -> Turn:
        """Her code, from the discounts collection. The checkout article is a different question."""

        payload = run_tool(
            session.phase,
            "list_customer_discounts",
            lambda: self._store.list_customer_discounts(session.customer_id),
        )
        required: list[str] = []
        for row in payload.get("discounts") or []:
            if not isinstance(row, dict):
                continue
            code = row.get("code")
            if isinstance(code, str) and code.strip():
                required.append(code.strip())
            label = row.get("percentLabel")
            if isinstance(label, str) and label.strip():
                required.append(label.strip())
        return Turn(
            template=customer_discounts(payload),
            instruction=(
                "They asked for their discount code. Copy the code from the JSON. "
                "If the list is empty, say there isn't one on the account. "
                "Do not invent a code, a percent, or an amount."
            ),
            tools=[
                ToolTrace(
                    name="list_customer_discounts",
                    summary="Read the discount codes on this account.",
                    payload=payload,
                )
            ],
            intent="policy",
            required=required,
            step="Step: your discount",
        )

    def _policy_turn(self, session: Session, message: str) -> Turn | None:
        """One article when the match is clear. A weak match asks which topic."""

        articles = [normalize_article(article) for article in self._store.policy_articles()]
        named = article_named(message, articles)
        if named:
            return self._article_turn(session, named)
        if not _has(session, "policy_question"):
            return None
        understanding = session.understanding
        chosen = understanding.article_id if understanding else None
        if chosen:
            return self._article_turn(session, chosen)
        return self._which_topic(articles)

    def _article_turn(self, session: Session, article_id: str) -> Turn:
        article = run_tool(
            session.phase,
            "get_policy_article",
            lambda: self._store.get_policy_article(article_id),
        )
        if not isinstance(article, dict) or not article.get("body"):
            articles = [normalize_article(item) for item in self._store.policy_articles()]
            return self._which_topic(articles)
        phrase = article.get("requiredPhrase")
        required = [phrase] if isinstance(phrase, str) and phrase.strip() else []
        intent = article.get("intent") if article.get("intent") in {
            "shipping",
            "password_reset",
            "policy",
        } else "policy"
        step = "Step: sign-in" if article.get("id") == "sign-in" else "Step: policy"
        return Turn(
            template=str(article["body"]),
            instruction=(
                "Say the article in the JSON and nothing past it. "
                "Do not add a day count, a dollar amount, or a code that is not in the article. "
                "Do not say a code was sent. Do not say whether an email address has an account. "
                "Do not cancel an order or change an address."
            ),
            tools=[
                ToolTrace(
                    name="get_policy_article",
                    summary=f"Read {article.get('topic') or article_id}.",
                    payload=article,
                )
            ],
            intent=intent,
            required=required,
            step=step,
        )

    def _faq_turn(self, session: Session, message: str) -> Turn | None:
        """A page of FAQ questions, or the article behind a clicked one. The phase does not
        change, so a return in progress picks up where it was on the next message."""

        picked = faq_pick(message)
        if picked is not None:
            session.understanding = None
            return self._article_turn(session, picked)
        start = faq_page(message)
        if start is None:
            return None
        session.understanding = None
        articles = [normalize_article(article) for article in self._store.policy_articles()]
        topics = {item["id"]: item["topic"] for item in articles}
        listed = [item for item in FAQ if item["articleId"] in topics]
        if not listed:
            return self._which_topic(articles)
        start = min(start, max(len(listed) - 1, 0))
        page = listed[start : start + FAQ_PAGE_SIZE]
        rest = len(listed) - (start + len(page))
        choices = [
            OrderChoice(
                order_id=f"{FAQ_CHOICE_PREFIX}{item['articleId']}",
                title=item["question"],
                mark=topics[item["articleId"]],
            )
            for item in page
        ]
        if rest > 0:
            choices.append(
                OrderChoice(
                    order_id=f"{FAQ_MORE_PREFIX}{start + len(page)}",
                    title="Show more questions",
                    mark=f"{rest} more",
                )
            )
        return Turn(
            template=faq_list(more=start > 0),
            instruction=(
                "They asked for the FAQ. Say in one short sentence that these are questions "
                "people ask, and they can pick one. Do not answer any of them. "
                "Do not list them; the buttons carry them."
            ),
            intent="clarify",
            step="Step: FAQ",
            choices=choices,
        )

    def _which_topic(self, articles: list[dict]) -> Turn:
        choices = [
            OrderChoice(order_id=article["id"], title=article["topic"], mark="Policy")
            for article in articles
            if article.get("id") and article.get("topic")
        ]
        return Turn(
            template=which_topic(),
            instruction=(
                "The question did not match one article. Ask which topic she means. "
                "Do not answer from memory. Do not invent a day count, a dollar amount, or a code."
            ),
            intent="clarify",
            step="Step: which topic",
            choices=choices,
        )

    def _too_late(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        orders, listed = self._listed(session)
        chosen = named_orders(message, orders)
        if len(chosen) == 1:
            return self._open_window(session, chosen[0], today, listed, now)
        return self._window_list(session, orders, today, listed)

    def _which_book(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        if _has(session, "password_reset"):
            return self._sign_in(session)
        orders, listed = self._listed(session)
        delivered = [order for order in orders if _is_delivered(order)]
        named = named_orders(message, orders)
        chosen = named or _pointed_order(session, orders)
        if not chosen:
            chosen = partial_title_matches(message, orders)
        session.found_by_search = not named
        if len(chosen) == 1:
            return self._open_window(session, chosen[0], today, listed, now)
        if len(delivered) == 1 and _offer_reply(session) == "accept":
            return self._open_window(session, delivered[0], today, listed, now)
        return self._window_list(session, orders, today, listed)

    def _exception_why(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        del today
        if _has(session, "password_reset"):
            return self._sign_in(session)
        if session.order_id is None or not session.title:
            session.phase = "which_book"
            return self._which_book(session, message, now.date(), now)
        if _offer_reply(session) == "accept":
            if isinstance(session.reason, str) and session.reason.strip():
                session.phase = "exception_offer"
                return self._offer_exception(session)
            return self._reask_exception(session, now.date())
        session.reason = message.strip()
        session.reason_kind, session.sentiment = _reason_labels(session)
        if _reason_topic(session) == "cheaper_elsewhere":
            return self._offer_price_match(session)
        session.phase = "exception_offer"
        return self._offer_exception(session)

    def _exception_offer(self, session: Session, message: str, today: date, now: datetime) -> Turn:
        # Asking for the card comes first: "yes, on my Visa" is not a yes to store credit.
        if _destination(session) == "original_payment":
            return self._exception_turn(session, confirm=False, card_asked=True)
        if _offer_reply(session) == "accept":
            session.destination = "store_credit"
            session.exception = True
            session.phase = "write"
            return self._write(session, today, now)
        if _offer_reply(session) == "unsure":
            return self._confirm_exception(session)
        return self._offer_exception(session)

    def _offer_exception(self, session: Session) -> Turn:
        return self._exception_turn(session, confirm=False)

    def _confirm_exception(self, session: Session) -> Turn:
        return self._exception_turn(session, confirm=True)

    def _exception_turn(self, session: Session, *, confirm: bool, card_asked: bool = False) -> Turn:
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
        if card_asked:
            payload["returnWindowDays"] = self._store.return_window_days()
            return Turn(
                template=exception_card(payload),
                instruction=(
                    "They asked for the refund on their card instead. Say kindly that this book is "
                    "past the return window in the JSON, so it can't go back on the card, and that "
                    "the one-time store credit is what you can do. Ask if they'd like it. Copy the "
                    "amount, the title, and the day count from the JSON. Do not repeat the earlier "
                    "offer word for word. Do not name the Visa or say a return is complete."
                ),
                tools=[
                    ToolTrace(
                        name="get_refund_options",
                        summary=f"Card not available for {payload['orderId']}; store credit only.",
                        payload=payload,
                    )
                ],
                required=[payload["title"], payload["amount"], "store credit"],
                step="Step: store credit exception",
            )
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
        orders = _without_completed_returns(
            run_tool(
                session.phase,
                "list_recent_orders",
                lambda: self._store.list_recent_orders(session.customer_id),
            )
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

    def _open_window(
        self, session: Session, selected: dict, today: date, listed: ToolTrace, now: datetime
    ) -> Turn:
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
        if not _is_delivered(detail) and is_in_progress(detail):
            return self._start_in_transit(session, detail, opened, [listed, opened], today, now)
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
            return self._start_return(session, detail, [listed, opened], today, now)
        return self._past_window(session, detail, opened, [listed, opened], today, now, card="Visa")


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


def _without_completed_returns(orders: list[dict]) -> list[dict]:
    """A completed return is already stored. Do not offer that order again."""

    return [order for order in orders if order.get("completedReturn") is not True]


def _is_delivered(order: dict) -> bool:
    status = order.get("status")
    if not isinstance(status, str) or status.strip().casefold() != "delivered":
        return False
    return isinstance(order.get("deliveredAt"), datetime)


def _marked_order(order: dict, today: date, days: int) -> dict:
    """Plain-language group from deliveredAt, the policy window, and status."""

    public = _public_order(order)
    public["returnWindowDays"] = days
    placed = order.get("placedAt")
    if isinstance(placed, datetime):
        public["placedLabel"] = short_date(placed, today)
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
        placed = order.get("placedLabel")
        choices.append(
            OrderChoice(
                order_id=order_id.strip(),
                title=title.strip(),
                mark=mark.strip(),
                placed=placed if isinstance(placed, str) and placed else None,
            )
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


def _has(session: Session, intent: str) -> bool:
    understanding = session.understanding
    return understanding is not None and intent in understanding.intents


def _about_kind(session: Session) -> str | None:
    understanding = session.understanding
    if understanding is None or "about_book" not in understanding.intents:
        return None
    return understanding.about


def _remember_match_details(session: Session) -> None:
    """Keep a price or store they mentioned, so it is not asked for again."""

    understanding = session.understanding
    if understanding is None:
        return
    if isinstance(understanding.match_price, (int, float)) and understanding.match_price > 0:
        session.match_price_cents = int(round(understanding.match_price * 100))
    if isinstance(understanding.match_store, str) and understanding.match_store.strip():
        session.match_store = understanding.match_store.strip()


def _pointed_order(session: Session, orders: list[dict]) -> list[dict]:
    """The one order Claude says they meant (by part of a title, a description, a misspelling)."""

    understanding = session.understanding
    order_id = understanding.order_id if understanding else None
    return [order for order in orders if order.get("orderId") == order_id] if order_id else []


def _reason_topic(session: Session) -> str:
    """What the reason is about. Claude's label, then the keywords."""

    understanding = session.understanding
    topic = understanding.reason_topic if understanding else None
    return topic or reason_topic(session.reason or "")


def _stated_reason(session: Session) -> str | None:
    """A reason they gave in the same sentence as the book, so Mara does not ask again."""

    understanding = session.understanding
    reason = understanding.reason if understanding else None
    return reason.strip() if isinstance(reason, str) and reason.strip() else None


def _ordered_window(session: Session) -> tuple[date, date] | None:
    """When they said they ordered it, as a window of days, or None."""

    understanding = session.understanding
    if understanding is None:
        return None
    after = understanding.ordered_after or understanding.ordered_before
    before = understanding.ordered_before or understanding.ordered_after
    if after is None or before is None:
        return None
    return after, before


def _placed_between(orders: list[dict], after: date, before: date) -> list[dict]:
    """Orders placed inside the window. A one-day window allows a day either side."""

    if (before - after).days < 2:
        after, before = after - timedelta(days=1), before + timedelta(days=1)
    placed = []
    for order in orders:
        moment = order.get("placedAt")
        if isinstance(moment, datetime) and after <= as_utc(moment).date() <= before:
            placed.append(order)
    return placed


def _destination(session: Session) -> str | None:
    understanding = session.understanding
    return understanding.destination if understanding else None


def _offer_reply(session: Session) -> str | None:
    understanding = session.understanding
    return understanding.offer_reply if understanding else None


def _reason_labels(session: Session) -> tuple[str, str | None]:
    """Claude's reason kind and sentiment. The late-delivery keywords back up a missing kind."""

    understanding = session.understanding
    kind = understanding.reason_kind if understanding else None
    sentiment = understanding.sentiment if understanding else None
    if kind is None:
        kind = classify_reason(session.reason or "")
    return kind, sentiment
