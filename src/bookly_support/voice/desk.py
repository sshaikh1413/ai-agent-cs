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

# A caller remembers the title and roughly when, not the order number, and a receipt id
# is unspeakable. The chat keeps both; the call leaves them out of what Piper says.
_UNSPOKEN = (
    # "BLY-44121 is The Night Circus." -> "The Night Circus."
    (re.compile(r"\b(?:[Oo]rder\s+)?BLY-\d+\s+is\s+(?=[A-Z])"), ""),
    (re.compile(r",\s*(?:order\s+)?BLY-\d+\s*,\s*", re.IGNORECASE), " "),
    (re.compile(r",\s*(?:order\s+)?BLY-\d+(?=\s*(?:[.!?;:]|$))", re.IGNORECASE), ""),
    (re.compile(r"\s*\(\s*(?:order\s+)?BLY-\d+\s*\)", re.IGNORECASE), ""),
    (re.compile(r"\border\s+(?:number\s+)?BLY-\d+", re.IGNORECASE), "order"),
    (re.compile(r"\bBLY-\d+", re.IGNORECASE), "that order"),
    (re.compile(r"\b[Rr]eceipt\s+rcpt_\w+\s+for\b"), "The refund for"),
    (re.compile(r"\b[Rr]eceipt\s+rcpt_\w+"), "The receipt"),
    # Any other sentence that carries a receipt id only reads the id out; the email line covers it.
    (re.compile(r"(?:^|(?<=[.!?]))\s*[^.!?]*\brcpt_\w+[^.!?]*[.!?]?"), ""),
)


_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_words(value: int) -> str:
    """0 to 999,999 in words: 16 -> "sixteen", 1299 -> "one thousand two hundred ninety-nine"."""

    if value < 20:
        return _ONES[value]
    if value < 100:
        tens, ones = divmod(value, 10)
        return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")
    if value < 1000:
        hundreds, rest = divmod(value, 100)
        return f"{_ONES[hundreds]} hundred" + (f" {number_words(rest)}" if rest else "")
    thousands, rest = divmod(value, 1000)
    return f"{number_words(thousands)} thousand" + (f" {number_words(rest)}" if rest else "")


def _spoken_money(match: re.Match[str]) -> str:
    whole = int(match.group(1).replace(",", ""))
    cents = int(match.group(2) or 0)
    dollars = f"{number_words(whole)} {'dollar' if whole == 1 else 'dollars'}"
    if not cents:
        return dollars
    return f"{dollars} and {number_words(cents)} {'cent' if cents == 1 else 'cents'}"


# "$16.99" (or a bare "16.99", which on this desk is always money) is said as words, and a
# card's last four are said digit by digit instead of as a number in the thousands.
_MONEY = re.compile(r"\$\s?(\d{1,6}(?:,\d{3})*)(?:\.(\d{2}))?|\b(?<![\d.])(\d{1,6})\.(\d{2})\b")
_LAST_FOUR = re.compile(r"\b(ending(?: in)?)\s+(\d{4})\b", re.IGNORECASE)


def spoken_amounts(text: str) -> str:
    def money(match: re.Match[str]) -> str:
        if match.group(1) is not None:
            return _spoken_money(match)
        return _spoken_money(re.match(r"(\d+)\.(\d{2})", f"{match.group(3)}.{match.group(4)}"))  # type: ignore[arg-type]

    text = _MONEY.sub(money, text)
    return _LAST_FOUR.sub(lambda m: f"ending in {' '.join(m.group(2))}", text)


# A caller cannot click a download. The receipt and the label go by email instead.
_DOWNLOAD = re.compile(r"\bdownload|\bready\b.*\b(?:receipt|label)\b|\b(?:receipt|label)\b.*\bready\b|\btracking\b", re.IGNORECASE)


def emailed_documents(text: str, *, receipt: bool, label: bool) -> str:
    """Swap "ready to download" lines for what a caller needs: it is in their email,
    and the refund follows once the book arrives."""

    if not receipt and not label:
        return text
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]
    kept = [sentence for sentence in sentences if not _DOWNLOAD.search(sentence)]
    if receipt and label:
        line = "I've emailed you your return confirmation receipt and shipping label."
    elif receipt:
        line = "I've emailed you your return confirmation receipt."
    else:
        line = "I've emailed you your shipping label."
    if receipt:
        line += " Once we receive the book, we'll process your refund."
    if not receipt:
        return " ".join([line, *kept])
    tail = [kept.pop()] if kept and kept[-1].endswith("?") else []
    return " ".join([*kept, line, *tail])


def unspoken_ids(text: str) -> str:
    """The sentence without order numbers or receipt ids, for the call only."""

    for pattern, replacement in _UNSPOKEN:
        text = pattern.sub(replacement, text)
    return re.sub(r"\s{2,}", " ", text).strip()


def spoken_text(reply: ChatReply) -> str:
    """What Piper may say.

    The checker reply is the whole sentence when it already names the books.
    Choice buttons whose titles were left off that sentence are spoken too,
    because a call cannot point at a button: the title and when it was ordered,
    never the order number. When the reply asks for the title or a date first,
    the list is not read. The step line, the tool name, and the tool JSON are
    never added here.
    """

    text = unspoken_ids(reply.reply.strip())
    text = emailed_documents(text, receipt=reply.receipt is not None, label=reply.label is not None)
    text = spoken_amounts(text)
    folded = text.casefold()
    extras: list[str] = []
    for choice in reply.choices if reply.read_choices else []:
        title = choice.title.strip()
        if not title or title.casefold() in folded:
            continue
        order_id = choice.order_id.strip()
        if _ORDER_ID.fullmatch(order_id) and choice.placed:
            extras.append(f"{title}, ordered {choice.placed}")
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
            {"order_id": choice.order_id, "title": choice.title, "mark": choice.mark, "placed": choice.placed}
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
