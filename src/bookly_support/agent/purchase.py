"""Buying a book through the desk: the offer Mara confirms, the order she places, and its
confirmation. Orders placed here ship free with 2-day delivery and are charged to the card
on file. The order is a real order on the account, so a status question finds it."""

from __future__ import annotations

import secrets
from datetime import datetime

from fpdf import FPDF

from bookly_support.agent.returns import format_amount

DELIVERY_DAYS = 2
DELIVERY = f"{DELIVERY_DAYS} business days"
PLACED_BY = "desk"
STATUS_DETAIL = "It's being packed now and ships free with 2-day delivery."


def book_offer(row: dict, payment: dict | None, address: str | None) -> dict | None:
    """What Mara confirms before ordering: title, author, price, free 2-day shipping, total, card, address."""

    price = row.get("priceCents")
    title = row.get("title")
    if not isinstance(price, int) or not isinstance(title, str) or not title.strip():
        return None
    brand = (payment or {}).get("brand")
    last4 = (payment or {}).get("last4")
    offer = {
        "title": title.strip(),
        "author": row.get("author"),
        "priceCents": price,
        "price": format_amount(price),
        "shippingCents": 0,
        "shipping": "free 2-day delivery",
        "totalCents": price,
        "total": format_amount(price),
        "delivery": DELIVERY,
        "deliveryDays": DELIVERY_DAYS,
        "address": address,
        "cardAvailable": bool(brand and last4),
    }
    if brand and last4:
        offer.update({"brand": brand, "last4": last4, "paymentMethodId": (payment or {}).get("_id")})
    return offer


def new_order_id() -> str:
    return f"BLY-{secrets.randbelow(90000) + 10000}"


def order_document(customer_id: str, offer: dict, address: str, purchase_key: str, order_id: str, now: datetime) -> dict:
    return {
        "_id": order_id,
        "customerId": customer_id,
        "placedAt": now,
        "deliveredAt": None,
        "status": "packing",
        "statusDetail": STATUS_DETAIL,
        "lines": [{"title": offer["title"], "qty": 1, "unitPriceCents": offer["priceCents"]}],
        "shippingCents": 0,
        "totalCents": offer["totalCents"],
        "refundableCents": offer["priceCents"],
        "paymentMethodId": offer.get("paymentMethodId"),
        "shipTo": address,
        "placedBy": PLACED_BY,
        "purchaseKey": purchase_key,
    }


def placed_result(order: dict, author: str | None, brand: str | None, last4: str | None) -> dict:
    """The tool payload after the order is placed (or found already placed)."""

    line = order["lines"][0]
    return {
        "status": "placed",
        "orderId": order["_id"],
        "title": line["title"],
        "author": author,
        "totalCents": order["totalCents"],
        "total": format_amount(order["totalCents"]),
        "shipping": "free 2-day delivery",
        "delivery": DELIVERY,
        "deliveryDays": DELIVERY_DAYS,
        "address": order.get("shipTo"),
        "brand": brand,
        "last4": last4,
    }


def render_order_confirmation(order: dict, customer: dict, author: str | None, brand: str | None, last4: str | None) -> bytes:
    """A one-page order confirmation. Every line is copied from the stored order."""

    line = order["lines"][0]
    placed = order.get("placedAt")
    rows = [
        ("Customer", str(customer.get("name") or "")),
        ("Order", order["_id"]),
        ("Title", line["title"] + (f" by {author}" if author else "")),
        ("Price", "$" + format_amount(line["unitPriceCents"])),
        ("Shipping", "Free 2-day delivery"),
        ("Total charged", "$" + format_amount(order["totalCents"]) + (f" to {brand} ending {last4}" if brand and last4 else "")),
        ("Ship to", str(order.get("shipTo") or "")),
        ("Arrives in", DELIVERY),
        ("Date", f"{placed:%B} {placed.day}, {placed.year}" if isinstance(placed, datetime) else ""),
    ]
    pdf = FPDF(format="letter", unit="mm")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Bookly", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, "Order confirmation", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for label, value in rows:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(38, 8, label.encode("latin-1", "replace").decode("latin-1"))
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 8, value.encode("latin-1", "replace").decode("latin-1"), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
