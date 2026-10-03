"""One-page return receipt. Every line is copied from stored records."""

from __future__ import annotations

from datetime import datetime

from fpdf import FPDF

from bookly_support.agent.returns import format_amount

_MONTHS = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

_REASON_LABELS = {
    "late_delivery": "Late delivery",
    "other": "Other",
}


class ReceiptFactsError(ValueError):
    """The stored return, order, and customer do not agree."""


def render_return_receipt(
    return_doc: dict,
    order: dict,
    customer: dict,
    receipt: dict,
) -> bytes:
    """Build a real one-page PDF. Nothing here is chosen by the model."""

    rows = receipt_rows(return_doc, order, customer, receipt)
    pdf = FPDF(format="letter", unit="mm")
    pdf.set_auto_page_break(auto=False)
    pdf.set_compression(False)
    pdf.set_margins(18, 18, 18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "Bookly", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, "Return receipt", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for label, value in rows:
        _row(pdf, label, value)
    return bytes(pdf.output())


def receipt_rows(
    return_doc: dict,
    order: dict,
    customer: dict,
    receipt: dict,
) -> list[tuple[str, str]]:
    """Labels and values for the receipt, in desk order."""

    _require_same(
        "customer",
        return_doc.get("customerId"),
        order.get("customerId"),
        receipt.get("customerId"),
        customer.get("_id"),
    )
    order_id = _require_same(
        "order",
        return_doc.get("orderId"),
        order.get("_id") or order.get("orderId"),
        receipt.get("orderId"),
    )
    receipt_id = _require_same("receipt", return_doc.get("receiptId"), receipt.get("_id"))
    title = _book_title(order, receipt)
    amount = _amount(return_doc, receipt)
    destination = _destination(return_doc, receipt)
    issued = _date_text(receipt.get("issuedAt")) or _date_text(return_doc.get("createdAt"))
    if issued is None:
        raise ReceiptFactsError("date")
    name = customer.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ReceiptFactsError("customer name")

    rows = [
        ("Customer", name.strip()),
        ("Order", order_id),
        ("Title", title),
    ]
    reason = _stored_text(return_doc.get("reason"))
    if reason:
        rows.append(("Reason", reason))
    label = _REASON_LABELS.get(return_doc.get("reasonKind"))
    if isinstance(return_doc.get("reasonKind"), str) and label:
        rows.append(("Reason label", label))
    rows.extend(
        [
            ("Refund", destination),
            ("Amount", amount),
            ("Receipt", receipt_id),
            ("Date", issued),
        ]
    )
    return rows


def _book_title(order: dict, receipt: dict) -> str:
    titles: list[str] = []
    lines = order.get("lines")
    if isinstance(lines, list):
        for line in lines:
            if not isinstance(line, dict):
                continue
            title = line.get("title")
            if isinstance(title, str) and title.strip():
                titles.append(title.strip())
    if len(titles) == 1:
        chosen = titles[0]
    elif len(titles) > 1:
        chosen = ", ".join(titles[:-1]) + " and " + titles[-1]
    else:
        title = order.get("title")
        chosen = title.strip() if isinstance(title, str) and title.strip() else ""
    stored = receipt.get("title")
    if isinstance(stored, str) and stored.strip():
        if chosen and chosen != stored.strip():
            raise ReceiptFactsError("title")
        if not chosen:
            chosen = stored.strip()
    if not chosen:
        raise ReceiptFactsError("title")
    return chosen


def _amount(return_doc: dict, receipt: dict) -> str:
    cents = _cents(return_doc.get("amountCents"), receipt.get("amountCents"))
    if cents is None:
        raise ReceiptFactsError("amount")
    return format_amount(cents)


def _cents(left: object, right: object) -> int | None:
    values = [item for item in (left, right) if item is not None]
    if not values or any(isinstance(item, bool) or not isinstance(item, int) for item in values):
        return None
    if any(item != values[0] for item in values):
        return None
    return values[0]


def _destination(return_doc: dict, receipt: dict) -> str:
    destination = _require_same(
        "destination",
        return_doc.get("destination"),
        receipt.get("destination"),
    )
    if destination == "store_credit":
        return "Store credit"
    if destination != "original_payment":
        raise ReceiptFactsError("destination")
    brand = receipt.get("brand")
    last4 = receipt.get("last4")
    if isinstance(brand, str) and brand.strip() and isinstance(last4, str) and last4.strip():
        return f"{brand.strip()} ending {last4.strip()}"
    return "Original payment"


def _date_text(value: object) -> str | None:
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if not 1 <= moment.month <= 12:
        return None
    return f"{_MONTHS[moment.month]} {moment.day}, {moment.year}"


def _stored_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def _require_same(field: str, *values: object) -> str:
    texts: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ReceiptFactsError(field)
        texts.append(value.strip())
    if any(item != texts[0] for item in texts):
        raise ReceiptFactsError(field)
    return texts[0]


def _latin(text: str) -> str:
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _row(pdf: FPDF, label: str, value: str) -> None:
    label = _latin(label)
    value = _latin(value)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(36, 8, label)
    pdf.set_font("Helvetica", "", 11)
    width = pdf.epw - 36
    if pdf.get_string_width(value) <= width:
        pdf.cell(width, 8, value, new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.multi_cell(width, 8, value, new_x="LMARGIN", new_y="NEXT")
