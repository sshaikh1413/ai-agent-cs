"""Closed phrases and order matching. The deterministic fallback for ``understand``.

In production Claude labels each message (see ``understand``). These functions
are the fallback when Claude is unavailable and the default in the pure tests.
Order ids and titles are always matched here, against the orders on file.
"""

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


_RETURN_WORD = re.compile(r"\breturns?\b")
_REFUSES_RETURN = re.compile(r"\b(?:do not|don't|dont)\s+want to return\b")


def asks_for_return(text: str) -> bool:
    """They want to start a return. "returned" and a refusal are not this."""

    lowered = _clean(text).replace("\u2019", "'").replace("\u2018", "'")
    if _REFUSES_RETURN.search(lowered):
        return False
    return _RETURN_WORD.search(lowered) is not None


_PARCEL_LABEL = re.compile(
    r"\bshipping\s+labels?\b"
    r"|\bsend\s+(?:me\s+)?the\s+labels?\b"
    r"|\bwhere(?:'s| is)\s+my\s+labels?\b",
)


def asks_for_parcel_label(text: str) -> bool:
    """They want the parcel label for a return, not a shipping-policy article.

    "How long does shipping take?" is not this. "shipping label?" is.
    """

    lowered = _clean(text).replace("\u2019", "'").replace("\u2018", "'")
    return _PARCEL_LABEL.search(lowered) is not None


_WHAT = r"what(?:['’]?s| is| was)"
_AUTHOR_Q = re.compile(r"\bauthor\b|\bwho wrote\b")
_ABOUT_Q = re.compile(rf"\b{_WHAT}\s+\S.+?\s+about\b")
_WHO_WROTE = re.compile(r"\bwho wrote\s+(.+?)(?:\s+and\b|[?.!]|$)")
_AUTHOR_OF = re.compile(r"\bauthor of\s+(.+?)(?:\s+and\b|[?.!]|$)")
_WHAT_ABOUT = re.compile(rf"\b{_WHAT}\s+(.+?)\s+about\b")
_PRONOUN_TITLE = re.compile(
    r"^(?:it|this|that|the book|this book|that book|the one|this one|that one)$"
)


_STATUS_ASK = (
    re.compile(r"\bwhere(?:'s| is)\s+(?:my|the|this)\s+(?:order|package|shipment)\b"),
    re.compile(r"\border status\b"),
    re.compile(r"\bwhat(?:'s| is)\s+the status\b"),
    re.compile(r"\bstatus of\b"),
    re.compile(r"\bhas\b.{0,80}\bshipped\b"),
    re.compile(r"\bis it out for delivery\b"),
    re.compile(r"\b(?:is|where)\b.{0,40}\bout for delivery\b"),
)

# Customer-facing trip statuses. "delivered" is not one of these.
_IN_PROGRESS = frozenset({"packing", "shipped", "on the way", "out for delivery"})


_OWN_DISCOUNT = re.compile(
    r"\bwhat(?:'s|s| is)\s+my\s+(?:discount|promo|coupon)(?:\s+code)?\b"
    r"|\bmy\s+(?:discount|promo|coupon)\s+code\b"
    r"|\bdo i have a (?:discount|promo|coupon)\b",
    re.IGNORECASE,
)


def asks_own_discount(text: str) -> bool:
    """She wants the code stored on her account, not the checkout instructions."""

    lowered = _clean(text).replace("\u2019", "'").replace("\u2018", "'")
    return _OWN_DISCOUNT.search(lowered) is not None


_WHERE_NAMED = re.compile(r"\bwhere(?:'s| is)\s+(?!do\b|can\b|should\b|would\b)")


def where_is_named(text: str) -> bool:
    """'Where is The Night Circus?' Names a thing. 'Where do you ship?' does not."""

    lowered = _clean(text).replace("\u2019", "'").replace("\u2018", "'")
    return _WHERE_NAMED.search(lowered) is not None


def asks_order_status(text: str) -> bool:
    """True when they ask where an order is, not why a book is coming back.

    The phrases are the ones a reader uses for tracking. A refund choice and
    a return reason do not match.
    """

    lowered = _clean(text).replace("\u2019", "'").replace("\u2018", "'")
    return any(pattern.search(lowered) for pattern in _STATUS_ASK)


def is_in_progress(order: dict) -> bool:
    return _status_label(order).casefold() in _IN_PROGRESS


def resolve_status(text: str, orders: list[dict]) -> tuple[str, list[dict]]:
    """Pick the order a status question is about.

    kind is one, several, missing, or none. A named id or title wins, including
    a delivered order. With no name, one in-progress order is the answer and
    two or more are a question.
    """

    mentioned = {match.upper() for match in _ORDER_ID.findall(text)}
    if mentioned:
        quoted = quoted_order_ids(text, orders)
        if len(quoted) == 1 and len(mentioned) == 1:
            return "one", quoted
        if len(quoted) > 1:
            return "several", quoted
        return "missing", []

    titles = title_matches(text, orders)
    if len(titles) == 1:
        return "one", titles
    if len(titles) > 1:
        return "several", titles
    if re.search(r"\bstatus of\b", _clean(text)) and not titles:
        return "missing", []

    progress = [order for order in orders if is_in_progress(order)]
    if len(progress) == 1:
        return "one", progress
    if len(progress) > 1:
        return "several", progress
    return "none", []


def _status_label(order: dict) -> str:
    status = order.get("status")
    if not isinstance(status, str):
        return ""
    return status.strip()


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


def asks_too_late(text: str) -> bool:
    """She is asking whether a return is already outside the window.

    A reason that a book arrived late is not this question. The machine only
    uses it while it is still choosing a book.
    """

    lowered = _clean(text)
    if "too late" in lowered:
        return True
    return re.search(r"\b(?:past|outside) the (?:return |30[- ]day )?window\b", lowered) is not None


_YES = {
    "yes",
    "yep",
    "yeah",
    "sure",
    "ok",
    "okay",
    "yes please",
    "that works",
    "that's fine",
    "thats fine",
    "that is fine",
    "that's acceptable",
    "thats acceptable",
    "that is acceptable",
    "acceptable",
    "i accept",
    "i'll take it",
    "ill take it",
    "i will take it",
    "sounds good",
    "do it",
    "go ahead",
}


def wants_return_in_play(text: str) -> bool:
    """Yes to the book already named. This is not a reason and not a card choice.

    After the window line, these words stay on that order. They do not pick
    a different book, and they do not describe what happened.
    """

    lowered = _clean(text).replace("\u2019", "'").replace("\u2018", "'").strip(".!")
    return lowered in {"yes", "i'll take it", "ill take it", "i will take it"}


# Neither a clear yes nor a clear no to the store-credit exception.
_EXCEPTION_HEDGES = frozenset({"why not", "i guess", "whatever"})


def is_exception_hedge(text: str) -> bool:
    """True for a shrug: not a clear yes and not a clear no."""

    cleaned = re.sub(r"\s+", " ", text).strip().lower()
    cleaned = cleaned.replace("\u2019", "'").replace("\u2018", "'")
    cleaned = cleaned.strip(" \t.!?,'\"\u2026")
    return cleaned in _EXCEPTION_HEDGES


def hedges_store_credit_exception(text: str) -> bool:
    """A shrug at the store-credit offer. Not a yes, and not a no."""

    return is_exception_hedge(text)


def accepts_store_credit_exception(text: str) -> bool:
    """Yes to the store-credit exception. A card phrase is not a yes.

    Closed yes phrases stay as they are. "Card is fine" stays on the offer.
    It does not select the Visa. "Why not", "I guess", and "whatever" are not
    a yes. Any other sentence is left to Claude in ``understand``; here it is
    not a yes. A clear no does not accept.
    """

    if is_exception_hedge(text):
        return False
    lowered = _clean(text).replace("\u2019", "'").replace("\u2018", "'").strip(".!")
    if is_decline(lowered):
        return False
    original, store = _destination_flags(lowered)
    if original and not store:
        return False
    if store and not original:
        return True
    if original and store:
        return False
    return lowered in _YES


def named_orders(text: str, orders: list[dict]) -> list[dict]:
    """Orders named by id or title. An id wins when one was typed."""

    quoted = quoted_order_ids(text, orders)
    if quoted:
        return quoted
    return title_matches(text, orders)


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

    Closed phrases only. Any other sentence is left to Claude in ``understand``.
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
