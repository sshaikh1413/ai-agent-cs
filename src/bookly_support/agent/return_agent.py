"""Signed-in return desk. The session customer is fixed. The model cannot choose it."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from bookly_support.agent.checker import accept_draft
from bookly_support.agent.machine import Machine, Session, Turn
from bookly_support.agent.phrasing import PROFILE_LINES, ClaudePhraser
from bookly_support.agent.provider import (
    ChatReply,
    ChatRequest,
    DeskInfo,
    DeskOrder,
    OrderChoice,
    ParcelLabel,
    ReceiptDownload,
    ToolTrace,
)
from bookly_support.agent.store import MongoStore
from bookly_support.agent.templates import opening_line
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
        prompts = [
            "I want to return a product",
            "Where is my order",
            "How long does shipping take?",
        ]
        prompt_order = _newest_delivered(orders)
        if customer_id == "cust_bob" and prompt_order:
            prompts.insert(1, f"I want to return {prompt_order['title']}")
        return DeskInfo(
            agent_name="Mara",
            customer_id=customer_id,
            customer_name=name,
            can_help=[
                f"Returns for {name}, who is already signed in.",
                "Where an order is, from the status stored on that order.",
                "Shipping, returns, sign-in, and the other shop policies, from Bookly's own articles.",
                "Why the book is coming back, before any refund.",
                "A refund to the original card or to store credit, after they choose.",
                "A one-page PDF receipt after the return is written.",
                "A too-late question lists every recent order, delivered or still on the way.",
                "A past-window book can be a one-time store-credit exception, with a receipt and a parcel label.",
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
            prompts=prompts,
            profile=list(PROFILE_LINES),
            opening=_welcome(*self._visit(customer_id), _customer_name(customer)),
        )

    def reply(self, request: ChatRequest) -> ChatReply:
        customer_id = _allow_customer(request.customer_id)
        session, started = self._session_for(customer_id, request.conversation_id)
        now = datetime.now(timezone.utc)
        turn = self._machine.step(session, request.message, today=now.date(), now=now)
        name = _customer_name(self.store.get_customer(customer_id))
        prior, memory = self._visit(customer_id)
        text = self._say(turn, request.message, name, memory)
        self.store.save_session(_session_doc(session))
        return ChatReply(
            reply=text,
            intent=turn.intent,  # type: ignore[arg-type]
            tools=[ToolTrace(name=tool.name, summary=tool.summary) for tool in turn.tools],  # type: ignore[arg-type]
            conversation_id=session.id,
            receipt=receipt_download(turn, customer_id),
            label=label_download(turn, customer_id),
            step=turn.step,
            opening=_welcome(prior, memory, name) if started else None,
            choices=[
                OrderChoice(order_id=choice.order_id, title=choice.title, mark=choice.mark)
                for choice in turn.choices
            ],
        )

    def _session_for(self, customer_id: str, conversation_id: str | None) -> tuple[Session, bool]:
        if conversation_id:
            document = self.store.load_session(customer_id, conversation_id)
            if document is not None and document.get("phase") != "closed":
                return _session(document), False
        document = self.store.create_session(customer_id)
        return _session(document), True

    def _visit(self, customer_id: str) -> tuple[dict | None, dict | None]:
        """The latest return, and a memory row only when a reason was stored."""

        prior = _prior_return(self.store, customer_id)
        memory = _phrase_memory(customer_id, prior)
        if memory is None:
            reader = getattr(self.store, "customer_memory", None)
            if reader is not None:
                memory = _phrase_memory(customer_id, reader(customer_id))
        return prior, memory

    def _say(
        self,
        turn: Turn,
        message: str,
        customer_name: str | None,
        memory: dict | None,
    ) -> str:
        draft = self.phraser.phrase(turn, message, customer_name, memory)
        prior_reason = memory.get("reason") if isinstance(memory, dict) else None
        reason = prior_reason if isinstance(prior_reason, str) and prior_reason.strip() else None
        return accept_draft(
            draft,
            turn.template,
            turn.payload,
            turn.required,
            message,
            reason,
        )


_RECEIPT_ID = re.compile(r"rcpt_[a-z0-9]+")
_LABEL_ID = re.compile(r"lbl_[a-z0-9]+")


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


def label_download(turn: Turn, customer_id: str) -> ParcelLabel | None:
    """Link for the parcel label written with a store-credit exception."""

    for tool in turn.tools:
        if tool.name != "start_return":
            continue
        payload = tool.payload
        if payload.get("status") != "completed" or not payload.get("exception"):
            continue
        label_id = payload.get("labelId")
        if not isinstance(label_id, str) or _LABEL_ID.fullmatch(label_id) is None:
            continue
        return ParcelLabel(
            label_id=label_id,
            url=f"/api/labels/{label_id}?customer_id={customer_id}",
        )
    return None


def _newest_delivered(orders: list[dict]) -> dict | None:
    """The newest delivered order. In-progress orders are not a return prompt."""

    for order in orders:
        status = order.get("status")
        if isinstance(status, str) and status.strip().casefold() == "delivered":
            return order
    return None


def _welcome(prior: dict | None, memory: dict | None, customer_name: str | None) -> str | None:
    """A human hello when they've been here. It does not quote the stored reason."""

    titled = False
    if isinstance(prior, dict):
        title = prior.get("title")
        titled = isinstance(title, str) and bool(title.strip())
    if memory is None and not titled:
        return None
    return opening_line(customer_name)


def _prior_return(store: MongoStore, customer_id: str) -> dict | None:
    latest = getattr(store, "latest_completed_return", None)
    if latest is None:
        return None
    prior = latest(customer_id)
    if not isinstance(prior, dict):
        return None
    return prior


def _phrase_memory(customer_id: str, record: dict | None) -> dict | None:
    """Memory for phrasing. No reason text means there is nothing to remember."""

    if not isinstance(record, dict):
        return None
    reason = record.get("reason")
    title = record.get("title")
    if not isinstance(reason, str) or not reason.strip():
        return None
    if not isinstance(title, str) or not title.strip():
        return None
    order_id = record.get("orderId")
    reason_kind = record.get("reasonKind")
    sentiment = record.get("sentiment")
    stored_customer = record.get("customerId")
    return {
        "customerId": stored_customer if isinstance(stored_customer, str) and stored_customer.strip() else customer_id,
        "orderId": order_id if isinstance(order_id, str) and order_id.strip() else None,
        "title": title.strip(),
        "reason": reason.strip(),
        "reasonKind": reason_kind.strip() if isinstance(reason_kind, str) and reason_kind.strip() else None,
        "sentiment": sentiment.strip() if isinstance(sentiment, str) and sentiment.strip() else None,
    }


def _customer_name(customer: dict | None) -> str | None:
    if not customer:
        return None
    name = customer.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    return name.strip()


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
        recommended_title=document.get("recommendedTitle"),
        exception=bool(document.get("exception")),
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
        "recommendedTitle": session.recommended_title,
        "exception": session.exception,
    }
