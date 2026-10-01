from bookly_support.agent.checker import accept_draft, facts_allowed, unsupported_facts
from bookly_support.agent.templates import completed, refund_choice

OPTIONS = {
    "results": [
        {
            "orderId": "BLY-22018",
            "title": "The Midnight Library",
            "refundableCents": 1699,
            "amount": "16.99",
            "originalPayment": {"available": True, "brand": "Visa", "last4": "4242"},
            "storeCredit": {"available": True, "refundableCents": 1699, "amount": "16.99"},
        }
    ]
}

RECEIPT = {
    "results": [
        {
            "status": "completed",
            "receiptId": "rcpt_abc123",
            "orderId": "BLY-22018",
            "title": "The Midnight Library",
            "amountCents": 1699,
            "amount": "16.99",
            "destination": "original_payment",
            "brand": "Visa",
            "last4": "4242",
        }
    ]
}


def test_card_tail_amount_and_ids_must_be_in_the_payload() -> None:
    assert facts_allowed("Visa ending 4242 for 16.99 on BLY-22018.", OPTIONS)
    assert "9999" in unsupported_facts("The card ends in 9999.", OPTIONS)
    assert "$18.00" in "".join(unsupported_facts("The refund is $18.00.", OPTIONS))
    assert any("BLY-99999" in item for item in unsupported_facts("Order BLY-99999.", OPTIONS))
    assert any("rcpt_deadbeef" in item for item in unsupported_facts("Receipt rcpt_deadbeef.", OPTIONS))


def test_dates_must_match_the_payload() -> None:
    payload = {"results": [{"placedAt": "2026-09-24T06:16:31Z", "orderId": "BLY-22018"}]}
    assert facts_allowed("Placed on September 24, 2026.", payload)
    assert unsupported_facts("Placed on September 1, 2026.", payload)


def test_completion_claim_requires_a_completed_receipt() -> None:
    assert unsupported_facts("Your return is complete.", OPTIONS)
    assert facts_allowed(
        "Your return is complete. Receipt rcpt_abc123 for The Midnight Library is 16.99 back to the Visa ending 4242.",
        RECEIPT,
    )


def test_ordinary_may_is_not_a_date() -> None:
    assert facts_allowed("I may help with a return.", {"results": []})


def test_templates_are_grounded() -> None:
    offer = refund_choice(OPTIONS["results"][0])
    done = completed(RECEIPT["results"][0])
    assert facts_allowed(offer, OPTIONS)
    assert facts_allowed(done, RECEIPT)
    assert accept_draft("I invented order BLY-00001.", offer, OPTIONS, ["The Midnight Library", "16.99", "4242"]) == offer
    assert "rcpt_abc123" in accept_draft("done", done, RECEIPT, ["rcpt_abc123", "16.99", "4242"])
