"""Match a customer sentence to an order or a refund destination."""

from __future__ import annotations

import re
from datetime import date

from bookly_support.agent.window import week_matches

_ORDER_ID = re.compile(r"\bBLY-\d+\b", re.IGNORECASE)
_WEEK = (
    "about a week ago",
    "about a week",
    "a week ago",
    "last week",
    "past week",
    "this past week",
)
_DECLINE = {
    "no",
    "nope",
    "nah",
    "no thanks",
    "no thank you",
    "nothing else",
    "nothing",
    "that's all",
    "thats all",
    "that is all",
    "i'm good",
    "im good",
    "all set",
    "no that's it",
    "no thats it",
    "no, that's all",
    "no, thats all",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def is_password_reset(text: str) -> bool:
    lowered = _clean(text)
    return "password" in lowered or "locked out" in lowered


def is_decline(text: str) -> bool:
    return _clean(text).strip(".!") in _DECLINE


_RECOMMEND_ASK = re.compile(r"\b(?:recommend(?:ation)?s?|suggest(?:ion)?s?)\b")


def asks_for_recommendation(text: str) -> bool:
    """A request for a book to read. A goodbye is not one of these."""

    return _RECOMMEND_ASK.search(_clean(text)) is not None


def mentions_week(text: str) -> bool:
    lowered = _clean(text)
    return any(phrase in lowered for phrase in _WEEK)


def quoted_order_ids(text: str, orders: list[dict]) -> list[dict]:
    known = {order["orderId"].upper(): order for order in orders}
    found: list[dict] = []
    seen: set[str] = set()
    for match in _ORDER_ID.findall(text):
        order_id = match.upper()
        if order_id in seen:
            continue
        seen.add(order_id)
        order = known.get(order_id)
        if order is not None:
            found.append(order)
    return found


def title_matches(text: str, orders: list[dict]) -> list[dict]:
    lowered = _clean(text)
    found: list[dict] = []
    for order in orders:
        title = str(order.get("title") or "").strip().lower()
        if title and title in lowered:
            found.append(order)
    return found


def destination_choice(text: str) -> str | None:
    lowered = _clean(text)
    if is_decline(lowered):
        return None
    store = any(
        phrase in lowered
        for phrase in ("store credit", "shop credit", "as credit", "in credit")
    )
    original = any(
        phrase in lowered
        for phrase in (
            "original payment",
            "original card",
            "payment method",
            "my card",
            "the card",
            "visa",
            "4242",
            "debit",
        )
    )
    if "credit card" in lowered:
        original = True
        if "store credit" not in lowered:
            store = False
    if original and store:
        return None
    if original:
        return "original_payment"
    if store:
        return "store_credit"
    return None


def resolve_order(text: str, orders: list[dict], today: date) -> tuple[str, list[dict]]:
    """Return (kind, matches).

    kind is one of: selected, ambiguous, week_none, list.
    A selected result has one order. The others ask her to choose.
    """

    quoted = quoted_order_ids(text, orders)
    if len(quoted) == 1:
        return "selected", quoted
    if len(quoted) > 1:
        return "ambiguous", quoted

    if mentions_week(text):
        matches = week_matches(orders, today)
        if len(matches) == 1:
            return "selected", matches
        if len(matches) > 1:
            return "ambiguous", matches
        return "week_none", orders

    titles = title_matches(text, orders)
    if len(titles) == 1:
        return "selected", titles
    if len(titles) > 1:
        return "ambiguous", titles
    return "list", orders
