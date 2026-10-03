from datetime import datetime, timezone

from bookly_support.agent.receipt_pdf import ReceiptFactsError, render_return_receipt
from bookly_support.agent.returns import commit_return


class MemoryReturns:
    def __init__(self) -> None:
        self.returns: dict[str, dict] = {}
        self.receipts: dict[str, dict] = {}

    def find_completed_return(self, customer_id: str, order_id: str) -> dict | None:
        for document in self.returns.values():
            if (
                document["customerId"] == customer_id
                and document["orderId"] == order_id
                and document["status"] == "completed"
            ):
                return document
        return None

    def find_receipt(self, customer_id: str, receipt_id: str) -> dict | None:
        document = self.receipts.get(receipt_id)
        if document is None or document["customerId"] != customer_id:
            return None
        return document

    def insert_return_and_receipt(self, return_doc: dict, receipt_doc: dict) -> None:
        self.returns[return_doc["_id"]] = dict(return_doc)
        self.receipts[receipt_doc["_id"]] = dict(receipt_doc)


ISSUED = datetime(2026, 10, 2, 15, tzinfo=timezone.utc)

ORDER = {
    "_id": "BLY-22044",
    "customerId": "cust_becky",
    "lines": [
        {
            "sku": "9780525620785",
            "title": "Mexican Gothic",
            "qty": 1,
            "unitPriceCents": 1699,
        }
    ],
}

CUSTOMER = {"_id": "cust_becky", "name": "Becky Alvarez", "email": "becky@example.com"}


def _receipt(receipt_id: str, return_id: str) -> dict:
    return {
        "_id": receipt_id,
        "returnId": return_id,
        "orderId": "BLY-22044",
        "customerId": "cust_becky",
        "title": "Mexican Gothic",
        "amountCents": 1699,
        "destination": "original_payment",
        "brand": "Visa",
        "last4": "4242",
        "issuedAt": ISSUED,
    }


def test_completed_return_keeps_the_reason_and_the_pdf_copies_it() -> None:
    repo = MemoryReturns()
    assert repo.find_completed_return("cust_becky", "BLY-22044") is None
    result = commit_return(
        repo,
        customer_id="cust_becky",
        order_id="BLY-22044",
        destination="original_payment",
        title="Mexican Gothic",
        amount_cents=1699,
        brand="Visa",
        last4="4242",
        now=ISSUED,
        new_ids=lambda: ("ret_demo", "rcpt_demo01ab"),
        reason="It arrived late",
        reason_kind="late_delivery",
    )
    stored = repo.returns[result["returnId"]]
    assert stored["status"] == "completed"
    assert stored["reason"] == "It arrived late"
    assert stored["reasonKind"] == "late_delivery"
    pdf = render_return_receipt(stored, ORDER, CUSTOMER, repo.receipts[stored["receiptId"]])
    assert pdf.startswith(b"%PDF")
    assert pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages") == 1
    assert stored["receiptId"].encode() in pdf
    assert stored["reason"].encode() in pdf
    assert b"Late delivery" in pdf
    assert b"Becky Alvarez" in pdf
    assert b"Mexican Gothic" in pdf
    assert b"BLY-22044" in pdf
    assert b"16.99" in pdf
    assert b"Visa ending 4242" in pdf
    assert b"October 2, 2026" in pdf


def test_pdf_for_the_existing_return_does_not_invent_a_reason() -> None:
    return_doc = {
        "_id": "ret_88b425d89d8d",
        "customerId": "cust_becky",
        "orderId": "BLY-22018",
        "destination": "original_payment",
        "amountCents": 1699,
        "status": "completed",
        "createdAt": datetime(2026, 10, 1, 8, 8, 42, tzinfo=timezone.utc),
        "receiptId": "rcpt_d38bda5f54f8",
    }
    order = {
        "_id": "BLY-22018",
        "customerId": "cust_becky",
        "lines": [{"title": "The Midnight Library", "qty": 1, "unitPriceCents": 1699}],
    }
    receipt = {
        "_id": "rcpt_d38bda5f54f8",
        "returnId": "ret_88b425d89d8d",
        "orderId": "BLY-22018",
        "customerId": "cust_becky",
        "title": "The Midnight Library",
        "amountCents": 1699,
        "destination": "original_payment",
        "brand": "Visa",
        "last4": "4242",
        "issuedAt": datetime(2026, 10, 1, 8, 8, 42, tzinfo=timezone.utc),
    }
    pdf = render_return_receipt(return_doc, order, CUSTOMER, receipt)
    assert pdf.startswith(b"%PDF")
    assert b"rcpt_d38bda5f54f8" in pdf
    assert b"The Midnight Library" in pdf
    assert b"It arrived late" not in pdf
    assert b"changed my mind" not in pdf
    assert b"Late delivery" not in pdf
    assert b"Reason" not in pdf


def test_pdf_refuses_a_mismatched_amount() -> None:
    return_doc = {
        "_id": "ret_demo",
        "customerId": "cust_becky",
        "orderId": "BLY-22044",
        "destination": "original_payment",
        "amountCents": 1699,
        "status": "completed",
        "createdAt": ISSUED,
        "receiptId": "rcpt_demo01ab",
        "reason": "It arrived late",
        "reasonKind": "late_delivery",
    }
    receipt = _receipt("rcpt_demo01ab", "ret_demo")
    receipt["amountCents"] = 2000
    try:
        render_return_receipt(return_doc, ORDER, CUSTOMER, receipt)
    except ReceiptFactsError:
        return
    raise AssertionError("a mismatched amount was rendered")
