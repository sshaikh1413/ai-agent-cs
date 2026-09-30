"""Mocked order, return, and password tools.

The demo agent calls these functions. They read the sample bookstore
records and return a short summary (shown with the reply) plus the
prose the agent can say. Nothing here talks to a vendor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from bookly_support.agent.catalog import (
    LABEL_FEE_CENTS,
    RETURN_WINDOW_DAYS,
    Order,
    add_business_days,
    book_phrase,
    format_date,
    format_money,
    load_orders,
)

ToolName = Literal["lookup_order", "start_return", "send_password_reset"]

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


@dataclass(frozen=True)
class ToolResult:
    name: ToolName
    summary: str
    detail: str


def _status_label(order: Order) -> str:
    labels = {
        "processing": "processing at the warehouse",
        "shipped": "shipped",
        "out_for_delivery": "out for delivery",
        "delivered": "delivered",
        "cancelled": "cancelled",
    }
    return labels[order.status]


def _window_clause(order: Order, today: date) -> str:
    if order.delivered_on is None:
        return "it has not been delivered, so the 30-day return window has not started"
    deadline = order.delivered_on + timedelta(days=RETURN_WINDOW_DAYS)
    left = (deadline - today).days
    if left >= 0:
        return (
            f"the 30-day return window is open through {format_date(deadline)} "
            f"({left} days left)"
        )
    return f"the 30-day return window closed on {format_date(deadline)}"


def _find(order_id: str, today: date) -> Order | None:
    target = order_id.upper()
    for order in load_orders(today):
        if order.id == target:
            return order
    return None


def _known_ids(today: date) -> str:
    return ", ".join(order.id for order in load_orders(today))


def _sample_emails(today: date) -> str:
    emails: list[str] = []
    for order in load_orders(today):
        if order.email not in emails:
            emails.append(order.email)
    return ", ".join(emails)


def describe_status(order: Order, today: date) -> str:
    books = book_phrase(order)
    card = f"The card on the order ends in {order.payment_last4}."
    if order.status == "processing":
        return (
            f"Order {order.id} for {order.customer_name} is still at the Columbus warehouse. "
            f"{books} was placed on {format_date(order.placed_on)} and has not shipped. "
            f"The charge is {format_money(order.total_cents)}, including "
            f"{format_money(order.shipping_cents)} standard shipping, on the card ending "
            f"{order.payment_last4}. Weekday orders placed before 2:00 pm Eastern ship the "
            f"next business day. I can cancel it while it is still at the warehouse."
        )
    if order.status == "shipped":
        assert order.shipped_on is not None
        listing = "The book is" if len(order.lines) == 1 else "The books are"
        if order.shipping_method == "standard":
            earliest = format_date(add_business_days(order.shipped_on, 5))
            latest = format_date(add_business_days(order.shipped_on, 7))
            arrival = (
                f"Standard shipping usually arrives 5–7 business days after the ship date, "
                f"which puts delivery between {earliest} and {latest}."
            )
        else:
            eta = format_date(add_business_days(order.shipped_on, 2))
            arrival = (
                f"Expedited shipping usually arrives 2 business days after the ship date, on {eta}."
            )
        return (
            f"Order {order.id} for {order.customer_name} shipped from Columbus on "
            f"{format_date(order.shipped_on)} with {order.carrier}. Tracking number "
            f"{order.tracking_number}. {listing} {books}. {arrival} It is not delivered yet, "
            f"so a return opens once it arrives. {card}"
        )
    if order.status == "out_for_delivery":
        assert order.shipped_on is not None
        service = "expedited" if order.shipping_method == "expedited" else "standard"
        return (
            f"Order {order.id} for {order.customer_name} is out for delivery today with "
            f"{order.carrier}. Tracking number {order.tracking_number}. The book is {books}. "
            f"It shipped on {format_date(order.shipped_on)} by {service} service. You can "
            f"refuse the package at the door if you don't want it. Otherwise a return is "
            f"available for 30 days after delivery. {card}"
        )
    if order.status == "delivered":
        assert order.delivered_on is not None
        clause = _window_clause(order, today)
        clause = clause[0].upper() + clause[1:]
        return (
            f"Order {order.id} for {order.customer_name} was delivered on "
            f"{format_date(order.delivered_on)}. The book is {books}. {clause}. "
            f"Tracking was {order.tracking_number}. {card}"
        )
    assert order.cancelled_on is not None and order.refund_issued_on is not None
    return (
        f"Order {order.id} for {order.customer_name} was cancelled on "
        f"{format_date(order.cancelled_on)}, before it shipped. {books} never left the "
        f"warehouse. We refunded {format_money(order.total_cents)} to the card ending "
        f"{order.payment_last4} on {format_date(order.refund_issued_on)}. Allow 5–7 "
        f"business days from that date for the refund to show on the card."
    )


def _mentions_damage(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in _DAMAGE_CUES)


def describe_return(order: Order, today: date, reason: str) -> str:
    damaged = _mentions_damage(reason)
    books = book_phrase(order)
    note = ""
    if "exchange" in reason.lower():
        note = (
            " Bookly doesn't exchange titles. A return refunds the original card, and a "
            "different book is a new order."
        )
    if order.status == "cancelled":
        assert order.refund_issued_on is not None
        return (
            f"Order {order.id} is already cancelled. The refund of "
            f"{format_money(order.total_cents)} was issued on "
            f"{format_date(order.refund_issued_on)} to the card ending {order.payment_last4}. "
            f"There isn't a second refund to open.{note}"
        )
    if order.status == "processing":
        return (
            f"Order {order.id} has not shipped, so this is a cancellation rather than a return. "
            f"Cancellation CX-{order.id.removeprefix('BLY-')} covers {books}. "
            f"{format_money(order.total_cents)} goes back to the card ending "
            f"{order.payment_last4} within 5–7 business days, and the warehouse will not ship "
            f"the book.{note}"
        )
    if order.status in {"shipped", "out_for_delivery"}:
        where = f"with {order.carrier} and has not been delivered"
        if order.status == "out_for_delivery":
            where = "out for delivery today and has not been marked delivered"
        return (
            f"Order {order.id} is {where}, so I can't open a return yet. You can refuse the "
            f"package, or start a return within 30 days after delivery. I also can't pull back "
            f"a shipment that is already in the carrier's hands.{note}"
        )
    assert order.delivered_on is not None
    deadline = order.delivered_on + timedelta(days=RETURN_WINDOW_DAYS)
    if deadline < today:
        if damaged:
            return (
                f"Order {order.id} was delivered on {format_date(order.delivered_on)}, and the "
                f"return window closed on {format_date(deadline)}, so I can't open a return "
                f"authorization for it. Damage found after the window needs a person to review. "
                f"Email help@booklybooks.example with photos of the book and order {order.id}.{note}"
            )
        return (
            f"Order {order.id}, {books}, was delivered on {format_date(order.delivered_on)}. "
            f"The return window closed on {format_date(deadline)}, so I can't open a return or "
            f"a refund for it.{note}"
        )
    if damaged:
        label = "The label is free because the book arrived damaged or was the wrong title."
        refund = (
            f"The refund is {format_money(order.subtotal_cents)}, the price of the book, "
            f"back to the card ending {order.payment_last4}."
        )
    else:
        label = (
            f"A prepaid label is {format_money(LABEL_FEE_CENTS)}, taken out of the refund. "
            "If the book arrived damaged or we sent the wrong title, tell me and the label is free."
        )
        refund = (
            f"The refund is {format_money(order.subtotal_cents)} minus the "
            f"{format_money(LABEL_FEE_CENTS)} label, back to the card ending {order.payment_last4} "
            "within 5–7 business days after check-in."
        )
    authorization = f"RA-{order.id.removeprefix('BLY-')}"
    return (
        f"I can open a return for order {order.id}, {books} "
        f"({format_money(order.subtotal_cents)}). It was delivered on "
        f"{format_date(order.delivered_on)}, and the window runs through {format_date(deadline)}.\n\n"
        f"Return authorization {authorization}. Pack the book in the condition it arrived, "
        f"dust jacket included. {label}\n\n"
        f"{refund}{note}"
    )


def _lookup_summary(order: Order, today: date) -> str:
    tracking = f" · {order.tracking_number}" if order.tracking_number else ""
    return (
        f"{order.id} · {order.customer_name} · {_status_label(order)} · "
        f"{book_phrase(order)} · {_window_clause(order, today)}{tracking}"
    )


def lookup_order(
    today: date,
    order_id: str | None = None,
    email: str | None = None,
) -> ToolResult:
    """Look up one order, or every sample order on an email."""

    if order_id:
        order = _find(order_id, today)
        if order is None:
            return ToolResult(
                name="lookup_order",
                summary=f"No sample order {order_id}.",
                detail=(
                    f"I don't have order {order_id} on this desk. The sample orders are "
                    f"{_known_ids(today)}."
                ),
            )
        return ToolResult(
            name="lookup_order",
            summary=_lookup_summary(order, today),
            detail=describe_status(order, today),
        )

    if email:
        normalized = email.lower()
        matches = [order for order in load_orders(today) if order.email == normalized]
        if not matches:
            return ToolResult(
                name="lookup_order",
                summary=f"No Bookly account for {normalized}.",
                detail=(
                    f"I don't have an account for {normalized} on this desk. Sample accounts "
                    f"are {_sample_emails(today)}."
                ),
            )
        if len(matches) == 1:
            return lookup_order(today, order_id=matches[0].id)
        lines = []
        for order in matches:
            extra = ""
            if order.status == "delivered":
                extra = f"; {_window_clause(order, today)}"
            lines.append(f"- {order.id}, {_status_label(order)}, {book_phrase(order)}{extra}")
        return ToolResult(
            name="lookup_order",
            summary=f"{normalized}: " + ", ".join(order.id for order in matches),
            detail=f"I found {len(matches)} orders for {normalized}:\n" + "\n".join(lines),
        )

    raise ValueError("lookup_order needs an order id or an email")


def _return_summary(order: Order, today: date, reason: str) -> str:
    if order.status == "delivered" and order.delivered_on is not None:
        deadline = order.delivered_on + timedelta(days=RETURN_WINDOW_DAYS)
        if deadline >= today:
            auth = f"RA-{order.id.removeprefix('BLY-')}"
            label = "label waived" if _mentions_damage(reason) else "label $4.50"
            return f"Filed {auth} for {order.id} ({label})."
        if _mentions_damage(reason):
            return f"Refused {order.id}: window closed, damage needs a person to review."
        return f"Refused {order.id}: return window closed."
    if order.status == "processing":
        return f"Filed CX-{order.id.removeprefix('BLY-')} to cancel {order.id} before shipment."
    if order.status == "cancelled":
        return f"{order.id} is already cancelled and refunded."
    return f"Did not file a return for {order.id}: it has not been delivered."


def start_return(order_id: str, reason: str, *, today: date) -> ToolResult:
    """File a return or cancellation, or explain why the sample order can't take one."""

    order = _find(order_id, today)
    if order is None:
        return ToolResult(
            name="start_return",
            summary=f"No sample order {order_id} to return.",
            detail=(
                f"I don't have order {order_id} on this desk, so I didn't file a return. "
                f"The sample orders are {_known_ids(today)}."
            ),
        )
    return ToolResult(
        name="start_return",
        summary=_return_summary(order, today, reason),
        detail=describe_return(order, today, reason),
    )


def send_password_reset(email: str, *, today: date) -> ToolResult:
    """Queue a password-reset link for a sample Bookly account."""

    normalized = email.lower()
    known = {order.email for order in load_orders(today)}
    if normalized not in known:
        return ToolResult(
            name="send_password_reset",
            summary=f"No Bookly account for {normalized}, so no link was queued.",
            detail=(
                f"I don't have an account for {normalized} on this desk, so I didn't send a "
                f"reset link. Sample accounts are {_sample_emails(today)}."
            ),
        )
    return ToolResult(
        name="send_password_reset",
        summary=f"Queued a 30-minute reset link for {normalized}.",
        detail=(
            f"A reset link is queued for {normalized}. I can't see or change the password. "
            f"Open the message from hello@booklybooks.example within 30 minutes, then choose "
            f"a new password of at least 10 characters, and not the one you used last. "
            f"If the message isn't there, check spam, then wait 10 minutes before you request "
            f"another link. A second request cancels the first link."
        ),
    )
