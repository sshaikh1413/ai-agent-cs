from datetime import datetime, timezone

from bookly_support.agent.returns import DuplicateReturn, commit_return, format_amount


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
        if self.find_completed_return(return_doc["customerId"], return_doc["orderId"]):
            raise DuplicateReturn
        self.returns[return_doc["_id"]] = dict(return_doc)
        self.receipts[receipt_doc["_id"]] = dict(receipt_doc)


def test_amount_is_dollars_from_cents() -> None:
    assert format_amount(1699) == "16.99"


def test_double_submit_returns_the_same_receipt() -> None:
    repo = MemoryReturns()
    ids = iter([("ret_one", "rcpt_one"), ("ret_two", "rcpt_two")])
    kwargs = dict(
        customer_id="cust_becky",
        order_id="BLY-22018",
        destination="original_payment",
        title="The Midnight Library",
        amount_cents=1699,
        brand="Visa",
        last4="4242",
        now=datetime(2026, 10, 1, tzinfo=timezone.utc),
        new_ids=lambda: next(ids),
    )
    first = commit_return(repo, **kwargs)
    second = commit_return(repo, **kwargs)
    assert first["status"] == "completed"
    assert second["receiptId"] == first["receiptId"] == "rcpt_one"
    assert second["amount"] == "16.99"
    assert len(repo.returns) == 1
    assert len(repo.receipts) == 1


def test_duplicate_key_returns_the_existing_receipt() -> None:
    repo = MemoryReturns()
    existing_return = {
        "_id": "ret_existing",
        "customerId": "cust_becky",
        "orderId": "BLY-22018",
        "status": "completed",
        "receiptId": "rcpt_existing",
    }
    existing_receipt = {
        "_id": "rcpt_existing",
        "customerId": "cust_becky",
        "orderId": "BLY-22018",
        "title": "The Midnight Library",
        "amountCents": 1699,
        "destination": "original_payment",
        "brand": "Visa",
        "last4": "4242",
    }

    class Race(MemoryReturns):
        def find_completed_return(self, customer_id: str, order_id: str) -> dict | None:
            found = super().find_completed_return(customer_id, order_id)
            if found is not None:
                return found
            return None

        def insert_return_and_receipt(self, return_doc: dict, receipt_doc: dict) -> None:
            self.returns[existing_return["_id"]] = existing_return
            self.receipts[existing_receipt["_id"]] = existing_receipt
            raise DuplicateReturn

    racing = Race()
    result = commit_return(
        racing,
        customer_id="cust_becky",
        order_id="BLY-22018",
        destination="original_payment",
        title="The Midnight Library",
        amount_cents=1699,
        brand="Visa",
        last4="4242",
        now=datetime(2026, 10, 1, tzinfo=timezone.utc),
        new_ids=lambda: ("ret_new", "rcpt_new"),
    )
    assert result["receiptId"] == "rcpt_existing"
    assert "ret_new" not in racing.returns
    assert repo.returns == {}
