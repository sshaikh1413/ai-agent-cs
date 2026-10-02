"""Safe replies built only from tool payloads."""

from __future__ import annotations

import re


def _listed(orders: list[dict]) -> str:
    parts = [f"{order['title']}, order {order['orderId']}" for order in orders]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def list_orders(orders: list[dict]) -> str:
    if not orders:
        return "There is nothing recent to return."
    return (
        f"I can help you return a recent order. I see {_listed(orders)}. "
        "Which one do you want to return?"
    )


def week_ambiguous(orders: list[dict]) -> str:
    return (
        f"I found more than one order from about a week ago: {_listed(orders)}. "
        "Which one should I return?"
    )


def week_none(orders: list[dict]) -> str:
    if not orders:
        return "I don't see an order from about a week ago, and there is nothing recent to return."
    return (
        "I don't see an order from about a week ago. "
        f"I can return {_listed(orders)}. Which one do you want?"
    )


def outside_window(order: dict) -> str:
    return (
        f"{order['title']}, order {order['orderId']}, is outside the "
        f"{order['returnWindowDays']}-day return window. {order['policy']}"
    )


def missing_order() -> str:
    return "I can't find that order on this account."


def ask_reason(order: dict) -> str:
    return (
        f"I can help return {order['title']}, order {order['orderId']}. "
        "What made you want to send it back?"
    )


def _sorry(sentiment: str | None) -> str:
    """Apology opening. Sentiment changes this wording and nothing about the offer."""

    if sentiment == "negative":
        return "I'm really sorry"
    if sentiment == "positive":
        return "Thank you for telling me. I'm sorry"
    return "I'm sorry"


def empathy_horror(title: str, recommendation: dict, sentiment: str | None = None) -> str:
    return (
        f"{_sorry(sentiment)} {title} was not a good read and was not scary. "
        f"If you'd like something else, try {recommendation['title']}."
    )


def empathy_horror_plain(title: str, sentiment: str | None = None) -> str:
    return (
        f"{_sorry(sentiment)} {title} was not a good read and was not scary. "
        "I don't have another title on the shelf to suggest."
    )


def late_apology(title: str, reason: str, sentiment: str | None = None) -> str:
    """Sorry the book was late, using the customer's own words.

    Sentiment changes only the opening. A gift or a birthday is not added here.
    Those words appear only when they are already in the reason.
    """

    return f"{_sorry(sentiment)} {title} arrived late. {_heard(reason)}"


def empathy_late(
    title: str,
    discount: dict,
    reason: str,
    sentiment: str | None = None,
) -> str:
    """Late-delivery apology plus the percent and code copied from the discount."""

    return (
        f"{late_apology(title, reason, sentiment)} "
        f"I can offer {discount['percentLabel']} off your next purchase with code {discount['code']}."
    )


def empathy_other(title: str, reason: str, sentiment: str | None = None) -> str:
    return f"{_sorry(sentiment)} {title} didn't work out. {_heard(reason)}"


def recommend_reply(recommendation: dict) -> str:
    """The one catalog title, or a line that names no book.

    The author and the summary stay off this offer. Those are answered only
    when the customer asks.
    """

    title = recommendation.get("title")
    if not isinstance(title, str) or not title.strip():
        return "I don't have another title on the shelf to suggest."
    return title.strip()


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def about_book(book: dict, kind: str) -> str:
    """Author, summary, or both, copied from the catalog row.

    A missing row, or a missing field, names no author and no plot.
    """

    title = _text(book.get("title")) or "this book"
    author = _text(book.get("author"))
    summary = _text(book.get("summary"))
    author_line = f"{title} is by {author}." if author else None
    if kind == "author":
        return author_line or "I don't have that on file."
    if kind == "summary":
        return summary or "I don't have that on file."
    parts = [line for line in (author_line, summary) if line]
    return " ".join(parts) if parts else "I don't have that on file."


def _heard(reason: str) -> str:
    words = re.findall(r"[A-Za-z']+", reason or "")
    text = " ".join(words).strip()
    if not text:
        return "I understand why you're sending it back."
    if len(text) > 140:
        shortened = text[:140].rsplit(" ", 1)[0]
        text = shortened or text[:140]
    return f"I hear you: {text}."


def refund_choice(options: dict) -> str:
    title = options["title"]
    order_id = options["orderId"]
    amount = options["amount"]
    original = options["originalPayment"]
    if original.get("available") and original.get("last4"):
        return (
            f"I can refund {title}, order {order_id}, for {amount} "
            f"to the {original['brand']} ending {original['last4']}, "
            f"or as store credit for {amount}. Which do you want?"
        )
    return (
        f"I can refund {title}, order {order_id}, for {amount} as store credit. "
        "The card on file is not available."
    )


def completed(receipt: dict) -> str:
    amount = receipt["amount"]
    title = receipt["title"]
    receipt_id = receipt["receiptId"]
    if receipt.get("destination") == "original_payment" and receipt.get("last4"):
        brand = receipt.get("brand") or "card"
        return (
            f"Your return is complete. Receipt {receipt_id} for {title} "
            f"is {amount} back to the {brand} ending {receipt['last4']}. "
            "The return receipt is ready to download. "
            "Anything else I can help with?"
        )
    return (
        f"Your return is complete. Receipt {receipt_id} for {title} "
        f"is {amount} in store credit. "
        "The return receipt is ready to download. "
        "Anything else I can help with?"
    )


def not_completed() -> str:
    return "The return did not complete. I don't have a receipt."


def ask_anything_else() -> str:
    return "Is there anything else I can help with?"


def closed() -> str:
    return "Okay. I'll close this chat."


def password_refused() -> str:
    return "I can help return a book from this account. I can't reset a password."


def opening_line(title: str, reason: str | None, customer_name: str | None = None) -> str:
    """First line of a new conversation. Title, and the stored reason only when one exists."""

    who = ""
    if isinstance(customer_name, str) and customer_name.strip():
        who = customer_name.strip().split()[0]
    if who:
        line = f"{who}, last time you returned {title}."
    else:
        line = f"Last time you returned {title}."
    if isinstance(reason, str) and reason.strip():
        said = " ".join(reason.split())
        return f"{line} You said: {said}."
    return line
