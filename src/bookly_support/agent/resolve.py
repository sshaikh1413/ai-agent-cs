"""Match a customer sentence to an order or a refund destination."""

from __future__ import annotations

import re
from datetime import date

from bookly_support.agent.destination import closest_destination
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


_WHAT = r"what(?:['’]?s| is| was)"
_AUTHOR_Q = re.compile(r"\bauthor\b|\bwho wrote\b")
_ABOUT_Q = re.compile(rf"\b{_WHAT}\s+\S.+?\s+about\b")
_WHO_WROTE = re.compile(r"\bwho wrote\s+(.+?)(?:\s+and\b|[?.!]|$)")
_AUTHOR_OF = re.compile(r"\bauthor of\s+(.+?)(?:\s+and\b|[?.!]|$)")
_WHAT_ABOUT = re.compile(rf"\b{_WHAT}\s+(.+?)\s+about\b")
_PRONOUN_TITLE = re.compile(
    r"^(?:it|this|that|the book|this book|that book|the one|this one|that one)$"
)


def book_question(text: str) -> str | None:
    """'author', 'summary', or 'both' when they ask who wrote a book or what it is about.

    A title may be named ("who wrote Becoming", "what's Becoming about") or left
    as a pronoun. "author" alone counts. A recommendation request does not.
    The machine answers only after they ask, and it does not treat the question
    as a return reason.
    """

    lowered = _clean(text)
    author = _AUTHOR_Q.search(lowered) is not None
    summary = _ABOUT_Q.search(lowered) is not None
    if author and summary:
        return "both"
    if author:
        return "author"
    if summary:
        return "summary"
    return None


def asked_title(text: str) -> str | None:
    """A title named in the question, or None when they mean the book in play.

    Pronouns ("it", "the book") are not a title. The caller looks the words up
    and, when no catalog row matches, says they are not on file.
    """

    lowered = _clean(text)
    found: list[str] = []
    for pattern in (_WHAT_ABOUT, _WHO_WROTE, _AUTHOR_OF):
        match = pattern.search(lowered)
        if match:
            found.append(match.group(1).strip(" \t\"'.,!?;:"))
    for candidate in found:
        if candidate and _PRONOUN_TITLE.fullmatch(candidate) is None:
            return candidate
    return None


def longest_catalog_title(text: str, titles: list[str]) -> str | None:
    """The longest catalog title written in the message, with its stored casing."""

    lowered = _clean(text)
    best: str | None = None
    for title in titles:
        name = title.strip()
        if not name:
            continue
        if re.search(rf"(?<!\w){re.escape(name.casefold())}(?!\w)", lowered):
            if best is None or len(name) > len(best):
                best = name
    return best


def mentions_week(text: str) -> bool:
    lowered = _clean(text)
    return any(phrase in lowered for phrase in _WEEK)


# Points at the one order already on screen. A list of two or more is not this.
_CONFIRM_SHOWN = re.compile(
    r"^(?:yes,?\s+)?(?:that one|that(?:'|’)?s the one)[.!?]*$"
)


def confirms_shown_order(text: str) -> bool:
    """True for "that's the one" and the close forms of that phrase."""

    return _CONFIRM_SHOWN.fullmatch(_clean(text)) is not None


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


def explicit_destination(text: str) -> str | None:
    """A closed phrase for original payment or store credit.

    None when the words are not one of those phrases, when they decline, or
    when both destinations are named. "card is fine" is not one of these phrases.
    """

    lowered = _clean(text)
    if is_decline(lowered):
        return None
    original, store = _destination_flags(lowered)
    if original and store:
        return None
    if original:
        return "original_payment"
    if store:
        return "store_credit"
    return None


def destination_choice(text: str) -> str | None:
    """Original payment, store credit, or None when Mara should ask again.

    Closed phrases stay as they are. Anything else is embedded and kept only
    when one destination is clearly ahead of the other.
    """

    lowered = _clean(text)
    if is_decline(lowered):
        return None
    original, store = _destination_flags(lowered)
    if original and store:
        return None
    if original:
        return "original_payment"
    if store:
        return "store_credit"
    return closest_destination(lowered)


def _destination_flags(lowered: str) -> tuple[bool, bool]:
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
    return original, store


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
    if len(orders) == 1 and confirms_shown_order(text):
        return "selected", orders
    return "list", orders
