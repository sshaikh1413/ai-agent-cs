"""The call speaks the checker-accepted reply. It does not grow a second set of rules."""

from __future__ import annotations

import re

from bookly_support.agent.provider import ChatReply, ChatRequest

# A bookstore phone line. This script names no order, price, or return window.
CALL_GREETING = (
    "Hi, thanks for calling Bookly. My name is Mara, and I'm your AI assistant. "
    "How can I help you?"
)

_ORDER_ID = re.compile(r"\bBLY-\d+\b", re.IGNORECASE)


def spoken_text(reply: ChatReply) -> str:
    """What Piper may say.

    The checker reply is the whole sentence when it already names the books.
    Choice buttons whose titles were left off that sentence are spoken too,
    because a call cannot point at a button. The step line, the tool name,
    and the tool JSON are never added here.
    """

    text = reply.reply.strip()
    folded = text.casefold()
    extras: list[str] = []
    for choice in reply.choices:
        title = choice.title.strip()
        if not title or title.casefold() in folded:
            continue
        order_id = choice.order_id.strip()
        if _ORDER_ID.fullmatch(order_id):
            extras.append(f"{title}, {order_id}")
        else:
            extras.append(title)
    if not extras:
        return text
    if text and text[-1] not in ".!?":
        text += "."
    return f"{text} {'. '.join(extras)}."


def reply_payload(reply: ChatReply) -> dict:
    """Panel fields. ``spoken`` is the only text that goes to Piper."""

    spoken = spoken_text(reply)
    return {
        "type": "reply",
        "text": reply.reply,
        "spoken": spoken,
        "intent": reply.intent,
        "step": reply.step,
        "conversation_id": reply.conversation_id,
        "tools": [{"name": tool.name, "summary": tool.summary} for tool in reply.tools],
        "choices": [
            {"order_id": choice.order_id, "title": choice.title, "mark": choice.mark}
            for choice in reply.choices
        ],
        "receipt": None if reply.receipt is None else reply.receipt.model_dump(),
        "label": None if reply.label is None else reply.label.model_dump(),
    }


def answer_transcript(agent: object, request: ChatRequest) -> ChatReply:
    """One customer turn, through the same ``reply`` the chat uses."""

    reply = agent.reply(request)  # type: ignore[attr-defined]
    if not isinstance(reply, ChatReply):
        raise TypeError("The desk reply was not a ChatReply.")
    return reply
