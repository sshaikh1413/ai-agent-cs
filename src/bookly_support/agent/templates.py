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


def empathy_horror(title: str, recommendation: dict) -> str:
    return (
        f"I'm sorry {title} was not a good read and was not scary. "
        f"If you'd like something else, try {recommendation['title']}."
    )


def empathy_horror_plain(title: str) -> str:
    return (
        f"I'm sorry {title} was not a good read and was not scary. "
        "I don't have another title on the shelf to suggest."
    )


def empathy_late(title: str, discount: dict) -> str:
    return (
        f"I'm sorry {title} arrived late and the gift was missed. "
        f"I can offer {discount['percentLabel']} off your next purchase with code {discount['code']}."
    )


def empathy_other(title: str, reason: str) -> str:
    return f"I'm sorry {title} didn't work out. {_heard(reason)}"


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
