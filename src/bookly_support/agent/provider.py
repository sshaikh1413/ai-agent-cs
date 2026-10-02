"""Server-side contract for Bookly's return desk.

``tools`` lists the Mongo tools the state machine actually ran.
The chat UI talks to ``frontend/src/agent/provider.ts``.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

Intent = Literal[
    "order_status",
    "return_refund",
    "shipping",
    "password_reset",
    "policy",
    "clarify",
    "out_of_scope",
]


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def stripped_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content is empty")
        return stripped


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    conversation_id: str | None = Field(default=None, max_length=80)
    customer_id: str | None = Field(default=None, max_length=40)

    @field_validator("message")
    @classmethod
    def stripped_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message is empty")
        return stripped

    @field_validator("conversation_id")
    @classmethod
    def stripped_conversation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("customer_id")
    @classmethod
    def allowed_customer(cls, value: str | None) -> str | None:
        from bookly_support.config import ALLOWED_CUSTOMER_IDS

        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if stripped not in ALLOWED_CUSTOMER_IDS:
            raise ValueError("customer is not on this desk")
        return stripped


ToolName = Literal[
    "list_recent_orders",
    "get_order",
    "get_refund_options",
    "start_return",
    "recommend_book",
    "issue_goodwill_discount",
]


class ToolTrace(BaseModel):
    """A tool the return machine ran while answering."""

    name: ToolName
    summary: str


class ReceiptDownload(BaseModel):
    """PDF for a return that start_return already completed."""

    receipt_id: str
    url: str


class ParcelLabel(BaseModel):
    """PDF parcel label written with a store-credit exception."""

    label_id: str
    url: str


class OrderChoice(BaseModel):
    """A book the customer can click. Taken from the tool payload, not the sentence."""

    order_id: str
    title: str
    mark: str


class ChatReply(BaseModel):
    reply: str
    intent: Intent
    tools: list[ToolTrace] = Field(default_factory=list)
    conversation_id: str | None = None
    receipt: ReceiptDownload | None = None
    label: ParcelLabel | None = None
    step: str
    opening: str | None = None
    choices: list[OrderChoice] = Field(default_factory=list)


class DeskOrder(BaseModel):
    id: str
    customer_name: str
    email: str
    summary: str


class DeskInfo(BaseModel):
    agent_name: str
    can_help: list[str]
    sample_orders: list[DeskOrder]
    prompts: list[str]
    customer_id: str
    customer_name: str
    profile: list[str]
    opening: str | None = None


class AgentProvider(Protocol):
    """Swap point for a live model and the order and returns APIs."""

    def reply(self, request: ChatRequest) -> ChatReply:
        """Answer one reader message using the conversation so far."""

    def desk(self, customer_id: str | None = None) -> DeskInfo:
        """Describe what this desk can do and which sample orders it knows."""
