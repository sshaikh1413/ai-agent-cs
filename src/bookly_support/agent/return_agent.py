"""Signed-in return desk. The session customer is fixed. The model cannot choose it."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from bookly_support.agent.checker import accept_draft
from bookly_support.agent.machine import Machine, Session, Turn
from bookly_support.agent.phrasing import ClaudePhraser
from bookly_support.agent.provider import (
    ChatReply,
    ChatRequest,
    DeskInfo,
    DeskOrder,
    ReceiptDownload,
    ToolTrace,
)
from bookly_support.agent.store import MongoStore
from bookly_support.config import ALLOWED_CUSTOMER_IDS, CUSTOMER_ID


class ReturnAgent:
    def __init__(self, store: MongoStore, phraser: ClaudePhraser) -> None:
        self.store = store
        self.phraser = phraser
        self._machine = Machine(store)

    def desk(self, customer_id: str = CUSTOMER_ID) -> DeskInfo:
        customer_id = _allow_customer(customer_id)
        customer = self.store.get_customer(customer_id)
        name = customer["name"] if customer and customer.get("name") else customer_id
        orders = self.store.list_recent_orders(customer_id)
        if customer_id == "cust_bob" and orders:
            follow_up = f"I want to return {orders[0]['title']}"
        else:
            follow_up = "the one from about a week ago"
        return DeskInfo(
            agent_name="Mara",
            customer_id=customer_id,
            customer_name=name,
            can_help=[
                f"Returns for {name}, who is already signed in.",
                "Why the book is coming back, before any refund.",
                "A refund to the original card or to store credit, after they choose.",
                "A one-page PDF receipt after the return is written.",
            ],
            sample_orders=[
                DeskOrder(
                    id=order["orderId"],
                    customer_name=name,
                    email=customer["email"] if customer else "",
                    summary=f"{order['status'] or 'order'} · {order['title']}",
                )
                for order in orders
            ],
            prompts=[
                "I want to return a product",
                follow_up,
            ],
        )

    def reply(self, request: ChatRequest) -> ChatReply:
        customer_id = _allow_customer(request.customer_id)
        session = self._session_for(customer_id, request.conversation_id)
        now = datetime.now(timezone.utc)
        turn = self._machine.step(session, request.message, today=now.date(), now=now)
        text = self._say(turn, request.message)
        self.store.save_session(_session_doc(session))
        return ChatReply(
            reply=text,
            intent=turn.intent,  # type: ignore[arg-type]
            tools=[ToolTrace(name=tool.name, summary=tool.summary) for tool in turn.tools],  # type: ignore[arg-type]
            conversation_id=session.id,
            receipt=receipt_download(turn, customer_id),
        )

    def _session_for(self, customer_id: str, conversation_id: str | None) -> Session:
        if conversation_id:
            document = self.store.load_session(customer_id, conversation_id)
            if document is not None and document.get("phase") != "closed":
                return _session(document)
        document = self.store.create_session(customer_id)
        return _session(document)

    def _say(self, turn: Turn, message: str) -> str:
        draft = self.phraser.phrase(turn, message)
        return accept_draft(draft, turn.template, turn.payload, turn.required)


_RECEIPT_ID = re.compile(r"rcpt_[a-z0-9]+")


def receipt_download(turn: Turn, customer_id: str) -> ReceiptDownload | None:
    """Link for the receipt this turn actually wrote. Absent until the return completes."""

    for tool in turn.tools:
        if tool.name != "start_return":
            continue
        payload = tool.payload
        if payload.get("status") != "completed":
            continue
        receipt_id = payload.get("receiptId")
        if not isinstance(receipt_id, str) or _RECEIPT_ID.fullmatch(receipt_id) is None:
            continue
        return ReceiptDownload(
            receipt_id=receipt_id,
            url=f"/api/receipts/{receipt_id}?customer_id={customer_id}",
        )
    return None


def _allow_customer(customer_id: str | None) -> str:
    if customer_id is None or not str(customer_id).strip():
        return CUSTOMER_ID
    cleaned = str(customer_id).strip()
    if cleaned not in ALLOWED_CUSTOMER_IDS:
        raise ValueError(cleaned)
    return cleaned


def _session(document: dict) -> Session:
    return Session(
        id=document["_id"],
        customer_id=document["customerId"],
        phase=document.get("phase") or "identify_order",
        order_id=document.get("orderId"),
        destination=document.get("destination"),
        return_id=document.get("returnId"),
        closed_at=document.get("closedAt"),
        reason=document.get("reason"),
        reason_kind=document.get("reasonKind"),
        sentiment=document.get("sentiment"),
        title=document.get("title"),
        genre=document.get("genre"),
    )


def _session_doc(session: Session) -> dict:
    return {
        "_id": session.id,
        "customerId": session.customer_id,
        "phase": session.phase,
        "orderId": session.order_id,
        "destination": session.destination,
        "returnId": session.return_id,
        "closedAt": session.closed_at,
        "reason": session.reason,
        "reasonKind": session.reason_kind,
        "sentiment": session.sentiment,
        "title": session.title,
        "genre": session.genre,
    }
