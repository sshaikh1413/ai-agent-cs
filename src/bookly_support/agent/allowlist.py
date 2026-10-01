"""Which tool the state machine may run in each phase."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

TOOL_NAMES = (
    "list_recent_orders",
    "get_order",
    "get_refund_options",
    "start_return",
)

Phase = str

_ALLOWED: dict[str, frozenset[str]] = {
    "identify_order": frozenset({"list_recent_orders", "get_order"}),
    "choose_destination": frozenset({"get_refund_options"}),
    "write": frozenset({"start_return"}),
    "done": frozenset(),
    "closed": frozenset(),
}


class ToolNotAllowed(Exception):
    def __init__(self, phase: str, tool: str) -> None:
        self.phase = phase
        self.tool = tool
        super().__init__(f"{tool} is not allowed in {phase}")


def allowed_tools(phase: str) -> frozenset[str]:
    return _ALLOWED.get(phase, frozenset())


T = TypeVar("T")


def run_tool(phase: str, tool: str, call: Callable[[], T]) -> T:
    if tool not in allowed_tools(phase):
        raise ToolNotAllowed(phase, tool)
    return call()
