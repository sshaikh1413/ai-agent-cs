"""Exact Mongo filters. Every customer-scoped query includes customerId."""

from __future__ import annotations

from bookly_support.config import POLICY_ID


def list_recent_orders(customer_id: str) -> dict[str, str]:
    return {"customerId": customer_id}


def get_order(customer_id: str, order_id: str) -> dict[str, str]:
    return {"_id": order_id, "customerId": customer_id}


def get_payment_method(customer_id: str, payment_method_id: str) -> dict[str, str]:
    return {"_id": payment_method_id, "customerId": customer_id}


def get_customer(customer_id: str) -> dict[str, str]:
    return {"_id": customer_id}


def completed_return(customer_id: str, order_id: str) -> dict[str, str]:
    return {"customerId": customer_id, "orderId": order_id, "status": "completed"}


def get_receipt(customer_id: str, receipt_id: str) -> dict[str, str]:
    return {"_id": receipt_id, "customerId": customer_id}


def get_policy() -> dict[str, str]:
    return {"_id": POLICY_ID}


def get_session(customer_id: str, conversation_id: str) -> dict[str, str]:
    return {"_id": conversation_id, "customerId": customer_id}
