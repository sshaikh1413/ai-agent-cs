"""Prepaid parcel label. Built from stored records.

The carrier name is ours. Nothing here calls FedEx, UPS, or any other carrier.
"""

from __future__ import annotations

from fpdf import FPDF

CARRIER_NAME = "Bookly Parcel"


class LabelFactsError(ValueError):
    """The return, customer, or address does not have what the label needs."""


def customer_address_lines(customer: dict) -> list[str]:
    """Street line and city line from the shipping address on the customer."""

    address = customer.get("shippingAddress")
    if not isinstance(address, dict):
        raise LabelFactsError("address")
    line1 = _text(address.get("line1"))
    city = _text(address.get("city"))
    region = _text(address.get("region"))
    postal = _text(address.get("postalCode"))
    if not line1 or not city or not region or not postal:
        raise LabelFactsError("address")
    return [line1, f"{city}, {region} {postal}"]


def customer_address_text(customer: dict) -> str:
    return ", ".join(customer_address_lines(customer))


def render_parcel_label(
    *,
    name: str,
    address_lines: list[str],
    carrier: str,
    tracking_number: str,
    order_id: str,
    title: str,
) -> bytes:
    """One-page label. Every line is copied from the return and the customer."""

    who = _text(name)
    shipped = [_text(line) for line in address_lines]
    if not who or not shipped or any(line is None for line in shipped):
        raise LabelFactsError("address")
    kept_carrier = _text(carrier)
    tracking = _text(tracking_number)
    kept_order = _text(order_id)
    kept_title = _text(title)
    if not kept_carrier or not tracking or not kept_order or not kept_title:
        raise LabelFactsError("label")

    pdf = FPDF(format="letter", unit="mm")
    pdf.set_auto_page_break(auto=False)
    pdf.set_compression(False)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Bookly", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, "Prepaid parcel label", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    rows = [
        ("Carrier", kept_carrier),
        ("Tracking", tracking),
        ("To", who),
        ("Order", kept_order),
        ("Title", kept_title),
    ]
    for label, value in rows:
        _row(pdf, label, value)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(36, 8, "Address")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(pdf.epw - 36, 8, _latin("\n".join(shipped)), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(
        0,
        6,
        "Issued by Bookly. No carrier was called.",
    )
    return bytes(pdf.output())


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _latin(text: str) -> str:
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _row(pdf: FPDF, label: str, value: str) -> None:
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(36, 8, _latin(label))
    pdf.set_font("Helvetica", "", 11)
    width = pdf.epw - 36
    text = _latin(value)
    if pdf.get_string_width(text) <= width:
        pdf.cell(width, 8, text, new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.multi_cell(width, 8, text, new_x="LMARGIN", new_y="NEXT")
