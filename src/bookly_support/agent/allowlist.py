"""Which tool the state machine may run in each phase."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

TOOL_NAMES = (
    "list_recent_orders",
    "get_order",
    "get_refund_options",
    "start_return",
    "recommend_book",
    "issue_goodwill_discount",
    "lookup_catalog",
    "get_policy_article",
    "list_customer_discounts",
    "issue_parcel_label",
)

Phase = str

# A status question reads orders and does not start a return, including while
# Mara is waiting for a reason or a refund choice.
_ORDER_READS = frozenset(
    {"list_recent_orders", "get_order", "lookup_catalog", "get_policy_article"}
)
_DISCOUNT_READ = frozenset({"list_customer_discounts"})
_LABEL = frozenset({"issue_parcel_label"})

_ALLOWED: dict[str, frozenset[str]] = {
    "identify_order": _ORDER_READS | _DISCOUNT_READ | _LABEL,
    "which_book": _ORDER_READS | _LABEL,
    "exception_why": _ORDER_READS | _LABEL,
    "exception_offer": _ORDER_READS | frozenset({"get_refund_options"}) | _LABEL,
    "ask_reason": _ORDER_READS | _LABEL,
    "empathy": frozenset({"recommend_book", "issue_goodwill_discount", "lookup_catalog"}) | _LABEL,
    "choose_destination": _ORDER_READS | frozenset({"get_refund_options"}) | _LABEL,
    "write": frozenset({"start_return", "lookup_catalog"}) | _LABEL,
    "done": _ORDER_READS | frozenset({"recommend_book"}) | _DISCOUNT_READ | _LABEL,
    "closed": _LABEL,
}


class ToolNotAllowed(Exception):
    def __init__(self, phase: str, tool: str) -> None:
        self.phase = phase
        self.tool = tool
        super().__init__(f"{tool} is not allowed in {phase}")


def allowed_tools(phase: str, reason_kind: str | None = None) -> frozenset[str]:
    """Tools for this phase. The discount also requires a late-delivery reason."""

    tools = set(_ALLOWED.get(phase, frozenset()))
    if reason_kind != "late_delivery":
        tools.discard("issue_goodwill_discount")
    return frozenset(tools)


T = TypeVar("T")


def run_tool(
    phase: str,
    tool: str,
    call: Callable[[], T],
    reason_kind: str | None = None,
) -> T:
    if tool not in allowed_tools(phase, reason_kind):
        raise ToolNotAllowed(phase, tool)
    return call()
