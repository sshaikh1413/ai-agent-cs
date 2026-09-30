"""Sample bookstore records for the demo desk.

Dates are computed from the clock the agent is given so the return
window stays believable whenever the app is run. Nothing here is a
live order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

RETURN_WINDOW_DAYS = 30
STANDARD_SHIPPING_CENTS = 595
EXPEDITED_SHIPPING_CENTS = 895
FREE_STANDARD_SUBTOTAL_CENTS = 3500
LABEL_FEE_CENTS = 450

OrderStatus = Literal[
    "processing",
    "shipped",
    "out_for_delivery",
    "delivered",
    "cancelled",
]
ShippingMethod = Literal["standard", "expedited"]

SHIPPING_POLICY = (
    "Bookly ships print books from the Columbus, Ohio warehouse, Monday through Friday. "
    "An order placed before 2:00 pm Eastern ships the next business day.\n\n"
    "Standard shipping takes 5–7 business days and costs $5.95. It is free when the "
    "books total $35.00 or more before tax.\n\n"
    "Expedited shipping takes 2 business days and costs $8.95.\n\n"
    "Tracking appears after the carrier scans the label, usually within one business "
    "day of shipment. Orders ship to US addresses. PO boxes can use standard shipping only.\n\n"
    "If you share an order number, I can tell you where that package is."
)

PASSWORD_RESET = (
    "I can't see or change your password. This is the reset that works on a Bookly account:\n\n"
    "1. Open the Bookly sign-in page and choose Forgot password.\n"
    "2. Enter the email on the account.\n"
    "3. Open the message from hello@booklybooks.example. The link lasts 30 minutes.\n"
    "4. Choose a new password of at least 10 characters, and not the one you used last.\n\n"
    "If the message isn't there, check spam, then wait 10 minutes before you request "
    "another link. A second request cancels the first link."
)

RETURN_POLICY = (
    "You have 30 days from the delivery date to send a print book back. It needs to "
    "arrive in the condition we sent it: no writing, no water damage, and the dust "
    "jacket if it came with one.\n\n"
    "The refund goes to the original card within 5–7 business days after the warehouse "
    "checks the book in. Return shipping is $4.50, taken out of the refund, unless the "
    "book arrived damaged or we sent the wrong title. Then the label is free.\n\n"
    "Bookly doesn't swap one title for another. A return refunds the original purchase, "
    "and a different book is a new order.\n\n"
    "Share an order number (it looks like BLY-10482) or the email on the account and "
    "I'll check that specific book."
)

DESK_PROMPTS = (
    "Where is order BLY-10482?",
    "I want to return a book.",
    "Where's my stuff?",
    "I forgot my Bookly password.",
)


@dataclass(frozen=True)
class OrderLine:
    title: str
    author: str
    quantity: int
    price_cents: int


@dataclass(frozen=True)
class Order:
    id: str
    email: str
    customer_name: str
    placed_on: date
    status: OrderStatus
    lines: tuple[OrderLine, ...]
    shipping_method: ShippingMethod
    payment_last4: str
    carrier: str | None = None
    tracking_number: str | None = None
    shipped_on: date | None = None
    delivered_on: date | None = None
    cancelled_on: date | None = None
    refund_issued_on: date | None = None

    @property
    def subtotal_cents(self) -> int:
        return sum(line.price_cents * line.quantity for line in self.lines)

    @property
    def shipping_cents(self) -> int:
        if self.shipping_method == "expedited":
            return EXPEDITED_SHIPPING_CENTS
        if self.subtotal_cents >= FREE_STANDARD_SUBTOTAL_CENTS:
            return 0
        return STANDARD_SHIPPING_CENTS

    @property
    def total_cents(self) -> int:
        return self.subtotal_cents + self.shipping_cents


def load_orders(today: date) -> tuple[Order, ...]:
    return (
        Order(
            id="BLY-10482",
            email="maya.chen@email.com",
            customer_name="Maya Chen",
            placed_on=today - timedelta(days=6),
            status="shipped",
            lines=(
                OrderLine("The Midnight Library", "Matt Haig", 1, 1800),
                OrderLine("Klara and the Sun", "Kazuo Ishiguro", 1, 1750),
            ),
            shipping_method="standard",
            payment_last4="4242",
            carrier="Bookly Parcel",
            tracking_number="BPX-4419082",
            shipped_on=today - timedelta(days=2),
        ),
        Order(
            id="BLY-10991",
            email="maya.chen@email.com",
            customer_name="Maya Chen",
            placed_on=today - timedelta(days=16),
            status="delivered",
            lines=(OrderLine("Project Hail Mary", "Andy Weir", 1, 1800),),
            shipping_method="expedited",
            payment_last4="4242",
            carrier="Bookly Parcel",
            tracking_number="BPX-4392201",
            shipped_on=today - timedelta(days=14),
            delivered_on=today - timedelta(days=12),
        ),
        Order(
            id="BLY-11004",
            email="jordan.okonkwo@email.com",
            customer_name="Jordan Okonkwo",
            placed_on=today - timedelta(days=54),
            status="delivered",
            lines=(
                OrderLine(
                    "Tomorrow, and Tomorrow, and Tomorrow",
                    "Gabrielle Zevin",
                    1,
                    1799,
                ),
            ),
            shipping_method="standard",
            payment_last4="1881",
            carrier="Bookly Parcel",
            tracking_number="BPX-4301188",
            shipped_on=today - timedelta(days=52),
            delivered_on=today - timedelta(days=47),
        ),
        Order(
            id="BLY-11120",
            email="jordan.okonkwo@email.com",
            customer_name="Jordan Okonkwo",
            placed_on=today - timedelta(days=1),
            status="processing",
            lines=(OrderLine("Circe", "Madeline Miller", 1, 1620),),
            shipping_method="standard",
            payment_last4="1881",
        ),
        Order(
            id="BLY-09877",
            email="sam.rivera@email.com",
            customer_name="Sam Rivera",
            placed_on=today - timedelta(days=20),
            status="cancelled",
            lines=(OrderLine("The House in the Cerulean Sea", "TJ Klune", 1, 1599),),
            shipping_method="standard",
            payment_last4="9033",
            cancelled_on=today - timedelta(days=19),
            refund_issued_on=today - timedelta(days=19),
        ),
        Order(
            id="BLY-11205",
            email="sam.rivera@email.com",
            customer_name="Sam Rivera",
            placed_on=today - timedelta(days=3),
            status="out_for_delivery",
            lines=(OrderLine("Piranesi", "Susanna Clarke", 1, 1600),),
            shipping_method="expedited",
            payment_last4="9033",
            carrier="Bookly Parcel",
            tracking_number="BPX-4481106",
            shipped_on=today - timedelta(days=2),
        ),
    )


def format_date(value: date) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def format_money(cents: int) -> str:
    return f"${cents // 100}.{cents % 100:02d}"


def add_business_days(start: date, days: int) -> date:
    current = start
    remaining = days
    while remaining:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def book_phrase(order: Order) -> str:
    parts = [f"{line.title} by {line.author}" for line in order.lines]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]
