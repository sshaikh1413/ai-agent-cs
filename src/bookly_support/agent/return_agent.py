"""Signed-in return desk. The session customer is fixed. The model cannot choose it."""

from __future__ import annotations

from datetime import datetime, timezone

from bookly_support.agent.checker import accept_draft
from bookly_support.agent.machine import Machine, Session, Turn
from bookly_support.agent.phrasing import ClaudePhraser
from bookly_support.agent.provider import ChatReply, ChatRequest, DeskInfo, DeskOrder, ToolTrace
from bookly_support.agent.store import MongoStore
from bookly_support.config import CUSTOMER_ID


class ReturnAgent:
    def __init__(self, store: MongoStore, phraser: ClaudePhraser, customer_id: str = CUSTOMER_ID) -> None:
        self.store = store
        self.phraser = phraser
        self.customer_id = customer_id
        self._machine = Machine(store)

    def desk(self) -> DeskInfo:
        customer = self.store.get_customer(self.customer_id)
        name = customer["name"] if customer and customer.get("name") else "Becky Alvarez"
        orders = self.store.list_recent_orders(self.customer_id)
        return DeskInfo(
            agent_name="Mara",
            can_help=[
                f"Returns for {name}, who is already signed in.",
                "Recent orders, then the one from about a week ago.",
                "A refund to the original card or to store credit, after she chooses.",
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
                "the one from about a week ago",
            ],
        )

    def reply(self, request: ChatRequest) -> ChatReply:
        session = self._session_for(request.conversation_id)
        now = datetime.now(timezone.utc)
        turn = self._machine.step(session, request.message, today=now.date(), now=now)
        text = self._say(turn, request.message)
        self.store.save_session(_session_doc(session))
        return ChatReply(
            reply=text,
            intent=turn.intent,  # type: ignore[arg-type]
            tools=[ToolTrace(name=tool.name, summary=tool.summary) for tool in turn.tools],  # type: ignore[arg-type]
            conversation_id=session.id,
        )

    def _session_for(self, conversation_id: str | None) -> Session:
        if conversation_id:
            document = self.store.load_session(self.customer_id, conversation_id)
            if document is not None and document.get("phase") != "closed":
                return _session(document)
        document = self.store.create_session(self.customer_id)
        return _session(document)

    def _say(self, turn: Turn, message: str) -> str:
        draft = self.phraser.phrase(turn, message)
        return accept_draft(draft, turn.template, turn.payload, turn.required)


def _session(document: dict) -> Session:
    return Session(
        id=document["_id"],
        customer_id=document["customerId"],
        phase=document.get("phase") or "identify_order",
        order_id=document.get("orderId"),
        destination=document.get("destination"),
        return_id=document.get("returnId"),
        closed_at=document.get("closedAt"),
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
    }
