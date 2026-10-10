"""Safe replies built only from tool payloads."""

from __future__ import annotations

import re


def list_orders(orders: list[dict]) -> str:
    """One short question. Titles and order ids stay on the choice list."""

    if not orders:
        return "There's nothing recent to return."
    return "Which book do you want to return?"


def ask_title_or_date() -> str:
    """Before listing every order: most people remember the title or roughly when."""

    return "Happy to help. Do you remember the book's title, or about when you ordered it?"


def wrong_book() -> str:
    """Mara named a book and they said no."""

    return "Sorry about that. What's the title, or about when you ordered it?"


def ask_title_again() -> str:
    """They did not want the list read out."""

    return "Okay. What's the title, or about when you ordered it?"


def could_not_find() -> str:
    """On a call: the book was not placed, so offer the list instead of reading it."""

    return "I couldn't find that book on your account. Would you like me to read your recent orders?"


def ordered_none_offer() -> str:
    """On a call: no order around that date, so offer the list instead of reading it."""

    return "I don't see an order from around then. Would you like me to read your recent orders?"


def ordered_several() -> str:
    """More than one order was placed around the date they gave."""

    return "I've got more than one order from around then. Which one is it?"


def ordered_none() -> str:
    """No order was placed around the date they gave. The full list follows."""

    return "I don't see an order from around then. Here's what I have. Which one is it?"


def handoff() -> str:
    """They asked for a person."""

    return "Of course. One moment, please, and I'll connect you with one of our agents."


def week_ambiguous(orders: list[dict]) -> str:
    if not orders:
        return "Which one should I return?"
    return (
        "I've got more than one from about a week ago. "
        "Which one should I return?"
    )


def week_none(orders: list[dict]) -> str:
    if not orders:
        return "I don't see an order from about a week ago, and there's nothing recent to return."
    return (
        "I don't see an order from about a week ago. "
        "Which book do you want to return?"
    )


def past_window(order: dict, *, card: str, ask: bool = True) -> str:
    """The delivered book is past the window: when it was ordered and delivered, how many
    days past the window it is now, and that it cannot go back on the card. Money is not
    offered here. ``ask`` adds the question about what happened."""

    ordered = order.get("placedLabel")
    delivered = order.get("deliveredLabel")
    title = f"{order['title']}, order {order['orderId']},"
    if ordered and delivered:
        lead = f"You ordered {title} on {ordered}, and it was delivered {delivered}."
    elif delivered:
        lead = f"{title[:-1]} was delivered {delivered}."
    else:
        lead = f"{title[:-1]} was delivered a while ago."
    days = order.get("daysPastWindow")
    window = order["returnWindowDays"]
    if isinstance(days, int) and days > 0:
        unit = "day" if days == 1 else "days"
        past = f"That's {days} {unit} past our {window}-day return window"
    else:
        past = f"That's past our {window}-day return window"
    text = f"{lead} {past}, so it cannot go back on the {card}."
    return f"{text} What is the reason for the return?" if ask else text


def ask_what_happened(order: dict) -> str:
    """Stay on the book already in play. Do not list the other orders."""

    return (
        f"I'll stay with {order['title']}, order {order['orderId']}. "
        "It cannot go back on the card. What is the reason for the return?"
    )


def missing_order() -> str:
    return "I can't find that order on this account."


def ask_reason(order: dict) -> str:
    return (
        f"Sure, I can return {order['title']}, order {order['orderId']}. "
        "What made you want to send it back?"
    )


def _sorry(sentiment: str | None) -> str:
    """Apology opening. Sentiment changes this wording and nothing about the offer."""

    if sentiment == "negative":
        return "I'm really sorry"
    if sentiment == "positive":
        return "Thank you for telling me. I'm sorry"
    return "I'm sorry"


# A horror book's line follows what they said: too scary, not scary enough, or anything else.
_HORROR = {
    "too_scary": "{sorry} {title} was too scary for you. Horror isn't for everyone.",
    "not_scary": "{sorry} {title} wasn't scary enough.",
}


def _horror_line(title: str, topic: str | None, sentiment: str | None) -> str:
    line = _HORROR.get(topic or "")
    if line is not None:
        return line.format(sorry=_sorry(sentiment), title=title)
    return empathy_other(title, topic, sentiment)


def empathy_horror(
    title: str, recommendation: dict, sentiment: str | None = None, topic: str | None = None
) -> str:
    """The acknowledgement for their reason, then one non-horror title."""

    other = "something gentler" if topic == "too_scary" else "something else"
    return f"{_horror_line(title, topic, sentiment)} If you'd like {other}, try {recommendation['title']}."


def empathy_horror_plain(title: str, sentiment: str | None = None, topic: str | None = None) -> str:
    return f"{_horror_line(title, topic, sentiment)} I don't have another title on the shelf to suggest."


def late_apology(title: str, reason: str, sentiment: str | None = None) -> str:
    """Sorry the book was late. Their sentence is not repeated back to them.

    Sentiment changes only the opening. A gift or a birthday is mentioned only
    when the reason already says so.
    """

    line = f"{_sorry(sentiment)} {title} arrived late."
    birthday = re.search(r"\bbirthdays?\b", reason or "", re.IGNORECASE) is not None
    gift = re.search(r"\bgifts?\b", reason or "", re.IGNORECASE) is not None
    if birthday and gift:
        line += " I know it was meant as a birthday gift, and that's a real letdown."
    elif birthday:
        line += " I know it was meant for a birthday, and that's a real letdown."
    elif gift:
        line += " I know it was meant as a gift, and that's a real letdown."
    return line


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


# One acknowledgement per kind of reason, in Mara's words. Their sentence is never quoted.
_ACKNOWLEDGE = {
    "not_for_me": "{sorry} {title} wasn't your kind of book. Not every story clicks, and that's okay.",
    "damaged": "{sorry} {title} reached you in that shape. That's not how a book should arrive.",
    "wrong_book": "{sorry} {title} wasn't the book you were expecting.",
    "duplicate": "No problem at all. Two copies of {title} is one more than anyone needs.",
    "changed_mind": "No problem at all. Plans change.",
}


def empathy_other(title: str, topic: str | None, sentiment: str | None = None) -> str:
    """A short, natural acknowledgement chosen from what the reason is about."""

    line = _ACKNOWLEDGE.get(topic or "")
    if line is None:
        return f"{_sorry(sentiment)} {title} didn't work out. Thanks for letting me know."
    return line.format(sorry=_sorry(sentiment), title=title)


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


def dollars(amount: object) -> str:
    """A stored amount ("16.99") as Mara writes it: "$16.99"."""

    text = str(amount).strip()
    return text if text.startswith("$") else f"${text}"


_BARE_AMOUNT = re.compile(r"(?<![$\d.,])(\d{1,6}(?:,\d{3})*\.\d{2})(?![\d%])")


def dollar_signs(text: str) -> str:
    """Every amount in a reply carries its dollar sign: "15.99" -> "$15.99".

    On this desk a number with two decimals is always money, so this runs on the
    final reply whether Claude or a template wrote it.
    """

    return _BARE_AMOUNT.sub(r"$\1", text)


def refund_choice(options: dict) -> str:
    title = options["title"]
    order_id = options["orderId"]
    amount = dollars(options["amount"])
    original = options["originalPayment"]
    if original.get("available") and original.get("last4"):
        return (
            f"I can put {amount} for {title}, order {order_id}, "
            f"back on the {original['brand']} ending {original['last4']}, "
            f"or keep it as store credit. Which do you want?"
        )
    return (
        f"I can put {amount} for {title}, order {order_id}, on store credit. "
        "The card on file isn't available."
    )


def completed(receipt: dict) -> str:
    amount = dollars(receipt["amount"])
    title = receipt["title"]
    receipt_id = receipt["receiptId"]
    if receipt.get("destination") == "original_payment" and receipt.get("last4"):
        brand = receipt.get("brand") or "card"
        return (
            f"Your return is complete. Receipt {receipt_id} for {title} "
            f"is {amount} back on the {brand} ending {receipt['last4']}. "
            "It's ready to download. "
            "Anything else I can help with?"
        )
    return (
        f"Your return is complete. Receipt {receipt_id} for {title} "
        f"is {amount} in store credit. "
        "It's ready to download. "
        "Anything else I can help with?"
    )


def not_completed() -> str:
    return "That return didn't go through. I don't have a receipt."


def ask_anything_else() -> str:
    return "Sure. Is there anything else I can help with?"


def closed() -> str:
    return "Okay. I'll close this chat."


def parcel_label_ready(label: dict) -> str:
    """The stored parcel label. Tracking and carrier are copied from the return."""

    line = (
        f"The parcel label for {label['title']}, order {label['orderId']}, is ready. "
        f"Tracking {label['trackingNumber']} on {label['carrier']}."
    )
    address = label.get("address")
    if isinstance(address, str) and address.strip():
        line += f" It goes to {address.strip()}."
    return line + " It's ready to download."


def no_parcel_label() -> str:
    """No completed return in this conversation, so no label is invented."""

    return "There isn't a parcel label yet, because no return is done."


def faq_list(*, more: bool = False) -> str:
    """One page of the FAQ. The buttons carry the questions."""

    if more:
        return "Here are more questions people ask. Pick one below."
    return "Here are the questions people ask most. Pick one below."


def which_topic() -> str:
    """A weak article match. The buttons carry the topic names."""

    return "Which topic do you mean? Pick one below, or type it."


def customer_discounts(payload: dict) -> str:
    """The codes stored for this customer. An empty list invents nothing."""

    rows = payload.get("discounts") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        return "I don't see a discount code on this account."
    parts: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = row.get("code")
        if not isinstance(code, str) or not code.strip():
            continue
        percent = row.get("percentLabel")
        order_id = row.get("orderId")
        if isinstance(percent, str) and percent.strip() and isinstance(order_id, str) and order_id.strip():
            parts.append(f"{code.strip()}, {percent.strip()} off, on order {order_id.strip()}")
        elif isinstance(percent, str) and percent.strip():
            parts.append(f"{code.strip()}, {percent.strip()} off")
        else:
            parts.append(code.strip())
    if not parts:
        return "I don't see a discount code on this account."
    if len(parts) == 1:
        return f"Your discount code is {parts[0]}."
    return "Your discount codes are " + " and ".join(parts) + "."


def _stored_detail(order: dict) -> str:
    detail = order.get("statusDetail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    return ""


def order_status(order: dict) -> str:
    """One order's stored status. A delivered order says it was delivered."""

    title = order["title"]
    order_id = order["orderId"]
    status = order.get("status")
    label = status.strip() if isinstance(status, str) else ""
    if label.casefold() == "delivered":
        line = f"{title}, order {order_id}, was {label}."
    elif label:
        line = f"{title}, order {order_id}, is {label}."
    else:
        line = f"{title}, order {order_id}."
    detail = _stored_detail(order)
    if detail:
        return f"{line} {detail}"
    return line


def order_status_choices(orders: list[dict]) -> str:
    """Several orders. Ask which one, and name each stored status."""

    lines = " ".join(order_status(order) for order in orders)
    return f"Which order? {lines}"


def no_order_in_progress() -> str:
    return "I don't see an order that's still on its way."


def delivered_window_list(orders: list[dict]) -> str:
    """Every recent order, with the mark computed from the order."""

    if not orders:
        return "I don't see a recent order on this account."
    lines = " ".join(_window_line(order) for order in orders)
    return f"Here are the recent orders. {lines} Which book did you mean?"


def _window_line(order: dict) -> str:
    mark = str(order.get("mark") or "").strip()
    title = order["title"]
    order_id = order["orderId"]
    label = order.get("deliveredLabel")
    if isinstance(label, str) and label.strip():
        head = f"{title}, order {order_id}, delivered {label.strip()}."
    else:
        head = f"{title}, order {order_id}."
    if mark:
        return f"{head} {mark}."
    return head


def still_sending(order: dict) -> str:
    """Not delivered. Repeat the stored trip status. Do not call it past the window."""

    status = order.get("status") or "still being sent"
    return (
        f"{order['title']}, order {order['orderId']}, has not been delivered. "
        f"It's {status}."
    )


def exception_offer(options: dict) -> str:
    """One offer: store credit for the refundable amount. The card is not offered."""

    return (
        f"I can make a one-time store credit exception for {dollars(options['amount'])} "
        f"on {options['title']}, order {options['orderId']}. Is that acceptable?"
    )


def exception_card(options: dict) -> str:
    """They asked for the card. Say why not, then the one offer again in new words."""

    return (
        f"I'm sorry, {options['title']} is past the {options['returnWindowDays']} days, "
        "so it can't go back on your card. What I can do is a one-time store credit "
        f"for {dollars(options['amount'])}. Would you like that?"
    )


def exception_confirm(options: dict) -> str:
    """A shrug is not a yes. Ask once, and stay on the amount and the order."""

    return (
        "I just want to confirm — you're good with the one-time store credit "
        f"for {dollars(options['amount'])} on {options['title']}, order {options['orderId']}, correct?"
    )


def exception_completed(receipt: dict) -> str:
    return (
        f"Your return is complete. Receipt {receipt['receiptId']} for {receipt['title']} "
        f"is {dollars(receipt['amount'])} in store credit. "
        "The receipt and the parcel label are ready to download. "
        "Anything else I can help with?"
    )


def opening_line(customer_name: str | None = None) -> str:
    """A welcome. The stored reason stays out of this sentence."""

    who = ""
    if isinstance(customer_name, str) and customer_name.strip():
        who = customer_name.strip().split()[0]
    if who:
        return f"{who}, it's good to see you again."
    return "It's good to see you again."
