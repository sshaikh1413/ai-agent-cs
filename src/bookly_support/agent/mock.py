"""Demo support agent.

Routes a conversation, then calls the mocked tools in ``tools.py``.
A return is not confirmed until the reader has given an order and a
reason. Replace this class in ``bookly_support.main`` when a real model
and the order APIs are chosen.
"""

from __future__ import annotations

import re
from datetime import date

from bookly_support.agent.catalog import (
    DESK_PROMPTS,
    PASSWORD_RESET,
    RETURN_POLICY,
    SHIPPING_POLICY,
    Order,
    book_phrase,
    load_orders,
)
from bookly_support.agent.provider import ChatReply, ChatRequest, ChatTurn, DeskInfo, DeskOrder, Intent, ToolTrace
from bookly_support.agent.tools import ToolResult, lookup_order, send_password_reset, start_return

_ORDER_RE = re.compile(r"\bbly[-\s]?(\d{5})\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})\b", re.IGNORECASE)

_TITLE_NEEDLES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("midnight library",), "BLY-10482"),
    (("klara",), "BLY-10482"),
    (("hail mary",), "BLY-10991"),
    (("tomorrow and tomorrow", "tomorrow, and tomorrow"), "BLY-11004"),
    (("circe",), "BLY-11120"),
    (("cerulean",), "BLY-09877"),
    (("piranesi",), "BLY-11205"),
)

_RETURN_CUES = (
    "return",
    "refund",
    "send it back",
    "send this back",
    "send the book back",
    "money back",
    "exchange",
    "cancel",
)
_ORDER_CUES = (
    "where is",
    "where's",
    "order status",
    "tracking",
    "track ",
    "track my",
    "shipped",
    "has it shipped",
    "out for delivery",
    "my order",
    "package",
    "when will",
    "status of",
    "arrive",
    "my stuff",
)
_SHIP_CUES = (
    "how long",
    "shipping",
    "ship to",
    "postage",
    "expedited",
    "business days",
    "po box",
    "delivery time",
)
_POLICY_CUES = (
    "policy",
    "policies",
    "return window",
    "how long do i have",
    "can i return",
)
_DAMAGE_CUES = (
    "damaged",
    "damage",
    "torn",
    "water damage",
    "waterlogged",
    "wrong title",
    "wrong book",
    "defective",
    "pages missing",
)
_REASON_CUES = _DAMAGE_CUES + (
    "changed my mind",
    "change my mind",
    "don't want",
    "do not want",
    "didn't like",
    "did not like",
    "no longer",
    "duplicate",
    "by mistake",
    "accident",
    "gift",
    "cancel",
)
_ANAPHORA = (
    " it",
    "it?",
    "that order",
    "this order",
    "the order",
    "my order",
    "that book",
    "this book",
    "the book",
    "that one",
    "this one",
    "same order",
)
_VAGUE = (
    "my stuff",
    "help with an order",
    "help with my order",
    "need help with an order",
    "about an order",
    "about my order",
    "check an order",
    "check on an order",
    "my package",
)
_THANKS = {"thanks", "thank you", "thanks mara", "ok", "okay", "got it"}
_GREETINGS = {
    "hi",
    "hello",
    "hey",
    "hiya",
    "good morning",
    "good afternoon",
    "good evening",
    "hi mara",
    "hello mara",
    "hey mara",
}
_NON_ANSWERS = _THANKS | {"yes", "yeah", "yep", "yup", "sure", "no", "nope"}

ASK_RETURN_ORDER = "What's the order number for the return?"
ASK_RETURN_REASON = "What's the reason for the return?"
ASK_RESET_EMAIL = "Which email is on the Bookly account?"

_GREETING_REPLY = (
    "Hello, I'm Mara. I look up Bookly orders, start returns and refunds, and answer "
    "questions about shipping, the return policy, and password reset. If you have an "
    "order number, it looks like BLY-10482."
)
_THANKS_REPLY = (
    "Glad to help. I can still look up an order, start a return, or walk through "
    "shipping and password reset."
)
_OUT_OF_SCOPE_REPLY = (
    "I can look up an order, start a return or refund, and explain shipping, the return "
    "policy, and password reset. I don't recommend books or change the email on an "
    "account. For that, write to help@booklybooks.example."
)
_CLARIFY_ORDER = (
    "I can look that up, but I don't want to guess which package you mean. "
    "What's the order number (it looks like BLY-10482), or the email on the account?"
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _has(text: str, cues: tuple[str, ...]) -> bool:
    return any(cue in text for cue in cues)


def _bare(text: str) -> str:
    return text.strip(" !.?").lower()


def _is_password(text: str) -> bool:
    if "password" in text or "locked out" in text:
        return True
    sign_in = any(phrase in text for phrase in ("log in", "login", "sign in", "signin"))
    return sign_in and "order" not in text


def _title_ids(text: str) -> list[str]:
    found: list[str] = []
    for needles, order_id in _TITLE_NEEDLES:
        if any(needle in text for needle in needles) and order_id not in found:
            found.append(order_id)
    return found


def _order_ids(text: str) -> list[str]:
    found: list[str] = []
    for match in _ORDER_RE.findall(text):
        order_id = f"BLY-{match}"
        if order_id not in found:
            found.append(order_id)
    return found


def _emails(text: str) -> list[str]:
    found: list[str] = []
    for match in _EMAIL_RE.findall(text):
        email = match.lower()
        if email not in found:
            found.append(email)
    return found


def _has_anaphora(text: str) -> bool:
    padded = f" {text}"
    return any(phrase in padded for phrase in _ANAPHORA)


def _has_identifier(text: str) -> bool:
    return bool(_order_ids(text) or _title_ids(text) or _emails(text))


def _has_reason(text: str) -> bool:
    return _has(text, _REASON_CUES)


def classify(message: str) -> Intent:
    text = _clean(message)
    if any(phrase in text for phrase in ("was i refunded", "refund status", "did i get a refund")):
        return "order_status"
    if _is_password(text):
        return "password_reset"
    if _bare(text) in _GREETINGS or _bare(text) in _THANKS:
        return "clarify"

    has_return = _has(text, _RETURN_CUES) or _has(text, _DAMAGE_CUES)
    has_ship = _has(text, _SHIP_CUES)
    named = _has_identifier(text)

    if any(phrase in text for phrase in ("recommend", "recommendation", "what should i read")):
        return "out_of_scope"
    if has_return and (_has_anaphora(text) or named):
        return "return_refund"
    if "shipping" in text and "return" not in text and "refund" not in text:
        return "shipping"
    if named:
        return "order_status"
    if has_return and "how long" in text:
        return "policy"
    if has_return and _has(text, _POLICY_CUES):
        if any(
            phrase in text
            for phrase in ("i want to return", "i'd like to return", "start a return", "need a refund")
        ):
            return "return_refund"
        return "policy"
    if _has(text, _POLICY_CUES) and not has_return:
        return "policy"
    if has_return:
        return "return_refund"
    if has_ship:
        return "shipping"
    if _has(text, _ORDER_CUES) or _has(text, _VAGUE):
        return "order_status"
    return "out_of_scope"


def _should_inherit(message: str, intent: Intent) -> bool:
    if intent not in {"order_status", "return_refund"}:
        return False
    text = _clean(message)
    if _has_identifier(text):
        return False
    if _has_anaphora(text) or _has(text, _DAMAGE_CUES):
        return True
    return _has(text, _RETURN_CUES)


def _latest_history_order_id(history_text: str, orders: tuple[Order, ...]) -> str | None:
    known = {order.id for order in orders}
    for order_id in reversed(_order_ids(history_text)):
        if order_id in known:
            return order_id
    for order_id in reversed(_title_ids(history_text)):
        if order_id in known:
            return order_id
    return None


def _last_assistant(history: list[ChatTurn]) -> str | None:
    for turn in reversed(history):
        if turn.role == "assistant":
            return turn.content
    return None


def _abandons_prompt(message: str) -> bool:
    """True when the reader started a different topic instead of answering."""

    if _bare(message) in _GREETINGS or _bare(message) in _THANKS:
        return True
    intent = classify(message)
    return intent in {"shipping", "password_reset", "policy"}


def _spoken(intent: Intent, detail: str, results: list[ToolResult]) -> ChatReply:
    if results:
        names = ", then ".join(result.name for result in results)
        reply = f"I used {names}. {detail}"
    else:
        reply = detail
    return ChatReply(
        reply=reply,
        intent=intent,
        tools=[ToolTrace(name=result.name, summary=result.summary) for result in results],
    )


def _status_label(order: Order) -> str:
    labels = {
        "processing": "Processing at the warehouse",
        "shipped": "Shipped",
        "out_for_delivery": "Out for delivery",
        "delivered": "Delivered",
        "cancelled": "Cancelled",
    }
    return labels[order.status]


class MockAgent:
    def __init__(self, today: date | None = None) -> None:
        self._today = today or date.today()

    def desk(self) -> DeskInfo:
        orders = load_orders(self._today)
        return DeskInfo(
            agent_name="Mara",
            can_help=[
                "Where a print order is, including tracking once the carrier has scanned it.",
                "Returns and refunds inside the 30-day window, and cancellations before a book ships.",
                "Shipping times and cost, the return policy, and password reset steps.",
            ],
            sample_orders=[
                DeskOrder(
                    id=order.id,
                    customer_name=order.customer_name,
                    email=order.email,
                    summary=f"{_status_label(order)} · {book_phrase(order)}",
                )
                for order in orders
            ],
            prompts=list(DESK_PROMPTS),
        )

    def reply(self, request: ChatRequest) -> ChatReply:
        previous = _last_assistant(request.history)
        if previous and not _abandons_prompt(request.message):
            if ASK_RETURN_REASON in previous:
                return self._answer_return_reason(request.message, previous)
            if ASK_RETURN_ORDER in previous:
                return self._answer_return_order(request.message)
            if ASK_RESET_EMAIL in previous:
                return self._answer_reset_email(request.message)

        intent = classify(request.message)
        text = _clean(request.message)

        if intent == "shipping":
            return ChatReply(reply=SHIPPING_POLICY, intent=intent)
        if intent == "policy":
            return ChatReply(reply=RETURN_POLICY, intent=intent)
        if intent == "password_reset":
            return self._password(request.message)
        if intent == "clarify":
            reply = _THANKS_REPLY if _bare(request.message) in _THANKS else _GREETING_REPLY
            return ChatReply(reply=reply, intent=intent)
        if _has(text, _VAGUE) and not _has_identifier(text) and not _has(text, _RETURN_CUES):
            return ChatReply(reply=_CLARIFY_ORDER, intent="clarify")
        if intent == "out_of_scope":
            return ChatReply(reply=_OUT_OF_SCOPE_REPLY, intent=intent)

        return self._from_entities(request, intent)

    def _password(self, message: str) -> ChatReply:
        emails = _emails(message)
        if not emails:
            return ChatReply(
                reply=(
                    "I can't see or change your password. "
                    f"{ASK_RESET_EMAIL} I'll use send_password_reset to queue a link. "
                    "The link lasts 30 minutes and comes from hello@booklybooks.example.\n\n"
                    + PASSWORD_RESET
                ),
                intent="password_reset",
            )
        result = send_password_reset(emails[0], today=self._today)
        return _spoken("password_reset", result.detail, [result])

    def _answer_reset_email(self, message: str) -> ChatReply:
        emails = _emails(message)
        if not emails:
            return ChatReply(
                reply=(
                    f"I still need the account email before I can send the link. {ASK_RESET_EMAIL}"
                ),
                intent="password_reset",
            )
        result = send_password_reset(emails[0], today=self._today)
        return _spoken("password_reset", result.detail, [result])

    def _answer_return_order(self, message: str) -> ChatReply:
        if _bare(message) in _NON_ANSWERS or not _has_identifier(_clean(message)):
            return ChatReply(
                reply=(
                    "I still need the order before I can look it up. "
                    f"{ASK_RETURN_ORDER} It looks like BLY-10482."
                ),
                intent="return_refund",
            )
        return self._from_entities(
            ChatRequest(message=message, history=[]),
            "return_refund",
        )

    def _answer_return_reason(self, message: str, previous: str) -> ChatReply:
        text = _clean(message)
        order_ids = [order_id for order_id in _order_ids(text) if order_id in self._by_id()]
        if not order_ids:
            order_ids = [order_id for order_id in _order_ids(previous) if order_id in self._by_id()]
        if _bare(message) in _NON_ANSWERS or not text:
            return ChatReply(
                reply=(
                    "I still need the reason before I confirm the return. "
                    f"{ASK_RETURN_REASON} Damaged, the wrong title, or you changed your mind "
                    "are all fine."
                ),
                intent="return_refund",
            )
        if not order_ids:
            return ChatReply(
                reply=f"I lost track of which book you meant. {ASK_RETURN_ORDER}",
                intent="return_refund",
            )
        reason = message.strip()
        if _order_ids(text) and not _has_reason(text):
            reason = message.strip()
        return self._finish_return(order_ids[0], reason)

    def _by_id(self) -> dict[str, Order]:
        return {order.id: order for order in load_orders(self._today)}

    def _from_entities(self, request: ChatRequest, intent: Intent) -> ChatReply:
        today = self._today
        orders = load_orders(today)
        by_id = {order.id: order for order in orders}
        text = _clean(request.message)
        explicit_ids = _order_ids(text)
        unknown_ids = [order_id for order_id in explicit_ids if order_id not in by_id]
        title_ids = [order_id for order_id in _title_ids(text) if order_id in by_id]
        emails = _emails(text)
        known_emails = {order.email for order in orders}
        unknown_emails = [email for email in emails if email not in known_emails]

        selected: list[Order] = []
        for order_id in explicit_ids:
            order = by_id.get(order_id)
            if order is not None and order not in selected:
                selected.append(order)
        if not selected:
            for order_id in title_ids:
                order = by_id[order_id]
                if order not in selected:
                    selected.append(order)

        if emails and selected and not unknown_emails:
            foreign = [order for order in selected if order.email not in emails]
            if foreign:
                owner = foreign[0]
                looked = lookup_order(today, order_id=owner.id)
                detail = (
                    f"{book_phrase(owner)} is order {owner.id} on {owner.customer_name}'s "
                    f"account ({owner.email}), not on {emails[0]}."
                )
                return _spoken(intent, detail, [looked])

        if not selected and emails and not unknown_emails:
            looked = lookup_order(today, email=emails[0])
            if intent == "return_refund" and looked.summary.count("BLY-") > 1:
                return _spoken(
                    intent,
                    f"{looked.detail}\n{ASK_RETURN_ORDER}",
                    [looked],
                )
            if intent == "return_refund" and "BLY-" in looked.summary:
                only = next(order for order in orders if order.email == emails[0])
                return self._continue_return(only, text)
            return _spoken("order_status" if intent != "return_refund" else intent, looked.detail, [looked])

        if not selected and not unknown_ids and not unknown_emails and _should_inherit(request.message, intent):
            history_text = "\n".join(turn.content for turn in request.history)
            inherited = _latest_history_order_id(history_text, orders)
            if inherited is not None:
                selected = [by_id[inherited]]

        if unknown_ids and not selected:
            missed = lookup_order(today, order_id=unknown_ids[0])
            return _spoken(intent, missed.detail, [missed])
        if unknown_emails and not selected:
            missed = lookup_order(today, email=unknown_emails[0])
            return _spoken(intent, missed.detail, [missed])
        if not selected:
            if intent == "return_refund":
                return ChatReply(
                    reply=(
                        "I can start a return, and I won't confirm it until I have the order "
                        f"and the reason. {ASK_RETURN_ORDER} It looks like BLY-10482. The email "
                        "on the account works too."
                    ),
                    intent="return_refund",
                )
            return ChatReply(reply=_CLARIFY_ORDER, intent="clarify")

        if len(selected) > 1:
            looked = lookup_order(today, email=selected[0].email)
            if intent == "return_refund":
                return _spoken(intent, f"{looked.detail}\n{ASK_RETURN_ORDER}", [looked])
            return _spoken("order_status", looked.detail, [looked])

        order = selected[0]
        if intent == "return_refund":
            return self._continue_return(order, text)
        looked = lookup_order(today, order_id=order.id)
        return _spoken("order_status", looked.detail, [looked])

    def _continue_return(self, order: Order, text: str) -> ChatReply:
        """Ask for a reason on a delivered order. Otherwise call start_return."""

        looked = lookup_order(self._today, order_id=order.id)
        if order.status == "delivered" and not _has_reason(text):
            detail = (
                f"I found {book_phrase(order)} on {order.id} for {order.customer_name}. "
                f"{ASK_RETURN_REASON} For example, it arrived damaged, we sent the wrong "
                "title, or you changed your mind."
            )
            return _spoken("return_refund", detail, [looked])
        reason = text if _has_reason(text) else "cancel before shipment"
        filed = start_return(order.id, reason, today=self._today)
        return _spoken("return_refund", filed.detail, [looked, filed])

    def _finish_return(self, order_id: str, reason: str) -> ChatReply:
        looked = lookup_order(self._today, order_id=order_id)
        filed = start_return(order_id, reason, today=self._today)
        return _spoken("return_refund", filed.detail, [looked, filed])
