"""Reject a draft that mentions a fact the tool payload did not contain."""

from __future__ import annotations

import json
import re
from datetime import date

_ORDER_ID = re.compile(r"\bBLY-\d+\b", re.IGNORECASE)
_RECEIPT_ID = re.compile(r"\brcpt_[a-z0-9]+\b", re.IGNORECASE)
_MONEY = re.compile(
    r"\$\s?(\d{1,6}(?:,\d{3})*)(?:\.(\d{2}))?|\b(\d+)\.(\d{2})\b"
)
_ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_FOUR_DIGIT = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_PERCENT = re.compile(r"(?<!\d)(\d{1,3})\s*%")
_GOODWILL_CODE = re.compile(r"\bBLY20-[A-F0-9]{8}\b", re.IGNORECASE)
_NAMED_CODE = re.compile(r"\bcode\s+([A-Za-z0-9][A-Za-z0-9-]{3,})\b", re.IGNORECASE)
_TITLE_PHRASE = re.compile(
    r"\b([A-Z][A-Za-z'’]+(?:\s+(?:[A-Z][A-Za-z'’]+|a|an|the|of|in|and|for|to|on)){1,10})\b"
)
_MID_CAP = re.compile(r"\b([A-Z][a-z]{2,})\b")

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_NAMED_DATE = re.compile(
    rf"\b(?P<month>{_MONTH_PATTERN})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<year>\d{{4}})\b",
    re.IGNORECASE,
)
_NAMED_DATE_DMY = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{_MONTH_PATTERN})\s+(?P<year>\d{{4}})\b",
    re.IGNORECASE,
)
# "may" is ordinary English, so a bare month word does not include it.
# "May 4, 2026" is still parsed by the named-date pattern.
_MONTH_WORD = re.compile(
    r"\b(?:january|february|march|april|june|july|august|september|october|november|december)\b",
    re.IGNORECASE,
)

_AUTHOR_CLAIM = re.compile(
    r"\b(?:written by|the author is|author is|(?:is|was) by)\s+"
    r"([A-Za-z][A-Za-z'’.-]*(?:\s+[A-Za-z][A-Za-z'’.-]*){0,4})",
    re.IGNORECASE,
)
_PLOT_CLAIM = re.compile(
    r"\b(?:it is about|it's about|it['’]s about|the book is about|this book is about|"
    r"the story (?:is|follows)|the plot is|it follows)\s+([^.]{8,})",
    re.IGNORECASE,
)
# Desk words that are not a plot. Used only when the payload carries a summary,
# so an about-book draft cannot swap in a different sentence.
_PLOT_STOP = {
    "a",
    "an",
    "the",
    "of",
    "in",
    "and",
    "for",
    "to",
    "on",
    "is",
    "by",
    "it",
    "its",
    "this",
    "that",
    "book",
    "books",
    "author",
    "about",
    "i",
    "don't",
    "dont",
    "have",
    "has",
    "had",
    "file",
    "not",
    "no",
    "we",
    "do",
    "does",
    "did",
    "with",
    "from",
    "or",
    "as",
    "at",
    "be",
    "was",
    "were",
    "you",
    "your",
    "me",
    "my",
    "she",
    "he",
    "her",
    "his",
    "they",
    "their",
    "them",
    "who",
    "what",
    "when",
    "where",
}

_COMPLETION_CLAIM = (
    "return is complete",
    "return's complete",
    "completed the return",
    "completed your return",
    "have completed the return",
    "return has started",
    "started the return",
    "return is filed",
    "filed the return",
    "here's your receipt",
    "here is your receipt",
)


def _walk(
    node: object,
    cents: set[int],
    dates: set[date],
    strings: list[str],
    percents: set[int],
    key: str | None = None,
) -> None:
    if isinstance(node, bool) or node is None:
        return
    if isinstance(node, int):
        cents.add(node)
        if key in {"percent", "percentOff"}:
            percents.add(node)
        return
    if isinstance(node, str):
        strings.append(node)
        if re.fullmatch(r"\d+\.\d{2}", node):
            dollars, fraction = node.split(".")
            cents.add(int(dollars) * 100 + int(fraction))
        for match in _ISO_DATE.finditer(node):
            dates.add(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        for match in _PERCENT.finditer(node):
            percents.add(int(match.group(1)))
        return
    if isinstance(node, dict):
        for child_key, value in node.items():
            _walk(value, cents, dates, strings, percents, child_key)
        return
    if isinstance(node, list):
        for value in node:
            _walk(value, cents, dates, strings, percents)


def _payload_facts(payload: object) -> tuple[str, set[int], set[date], set[int]]:
    cents: set[int] = set()
    dates: set[date] = set()
    strings: list[str] = []
    percents: set[int] = set()
    _walk(payload, cents, dates, strings, percents)
    blob = json.dumps(payload, default=str).lower()
    return blob, cents, dates, percents


def _money_cents(match: re.Match[str]) -> int | None:
    if match.group(3) is not None:
        return int(match.group(3)) * 100 + int(match.group(4))
    dollars = int(match.group(1).replace(",", ""))
    fraction = match.group(2)
    if fraction is None:
        return dollars * 100
    return dollars * 100 + int(fraction)


def _named_date(match: re.Match[str]) -> date | None:
    month = _MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    try:
        return date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        return None


def completion_is_grounded(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    results = payload.get("results")
    if not isinstance(results, list):
        return False
    for result in results:
        if not isinstance(result, dict):
            continue
        if result.get("status") == "completed" and result.get("receiptId"):
            return True
    return False


def unsupported_facts(reply: str, payload: object) -> list[str]:
    """Fact strings in the reply that the tool payload does not support."""

    blob, cents, dates, percents = _payload_facts(payload)
    problems: list[str] = []

    for match in _ORDER_ID.finditer(reply):
        if match.group(0).lower() not in blob:
            problems.append(match.group(0))

    for match in _RECEIPT_ID.finditer(reply):
        if match.group(0).lower() not in blob:
            problems.append(match.group(0))

    for match in _MONEY.finditer(reply):
        amount = _money_cents(match)
        if amount is None or amount not in cents:
            problems.append(match.group(0))

    parsed_spans: list[tuple[int, int]] = []
    date_patterns = (_NAMED_DATE, _NAMED_DATE_DMY, _ISO_DATE, _SLASH_DATE)
    for pattern in date_patterns:
        for match in pattern.finditer(reply):
            if pattern in {_NAMED_DATE, _NAMED_DATE_DMY}:
                found = _named_date(match)
            elif pattern is _ISO_DATE:
                found = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            else:
                try:
                    found = date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
                except ValueError:
                    found = None
            parsed_spans.append((match.start(), match.end()))
            if found is None or found not in dates:
                problems.append(match.group(0))

    for match in _MONTH_WORD.finditer(reply):
        if any(start <= match.start() and match.end() <= end for start, end in parsed_spans):
            continue
        problems.append(match.group(0))

    masked = reply
    for pattern in (_ORDER_ID, _RECEIPT_ID, _MONEY, _NAMED_DATE, _NAMED_DATE_DMY, _ISO_DATE, _SLASH_DATE):
        masked = pattern.sub(lambda match: " " * len(match.group(0)), masked)
    for match in _FOUR_DIGIT.finditer(masked):
        if match.group(1) not in blob:
            problems.append(match.group(1))

    for match in _PERCENT.finditer(reply):
        if int(match.group(1)) not in percents:
            problems.append(match.group(0))

    for match in _GOODWILL_CODE.finditer(reply):
        if match.group(0).lower() not in blob:
            problems.append(match.group(0))

    for match in _NAMED_CODE.finditer(reply):
        if match.group(1).lower() not in blob:
            problems.append(match.group(1))

    for match in _TITLE_PHRASE.finditer(reply):
        phrase = match.group(1)
        if any(word.lower() in _MONTHS for word in re.findall(r"[A-Za-z]+", phrase)):
            continue
        if phrase.lower() not in blob:
            problems.append(phrase)

    for match in _MID_CAP.finditer(reply):
        if _is_sentence_start(reply, match.start()):
            continue
        word = match.group(1)
        if word.lower() in _MONTHS or word.lower() in blob:
            continue
        problems.append(word)

    lowered = reply.lower()
    if any(phrase in lowered for phrase in _COMPLETION_CLAIM) or (
        "receipt" in lowered and "rcpt_" in lowered
    ):
        if not completion_is_grounded(payload):
            problems.append("completion")

    problems.extend(_ungrounded_author_or_plot(reply, payload, blob))
    problems.extend(_ungrounded_occasion(reply, payload))
    problems.extend(_ungrounded_fulfillment_status(reply, blob))
    problems.extend(_ungrounded_delivered_claim(reply, payload))
    problems.extend(_ungrounded_past_window(reply, payload))
    problems.extend(_ungrounded_status_detail(reply, payload, blob))
    problems.extend(_ungrounded_card_refund(reply, payload))
    problems.extend(_ungrounded_carrier(reply, blob))
    problems.extend(_ungrounded_day_count(reply, payload))
    problems.extend(_ungrounded_email(reply, blob))
    problems.extend(_ungrounded_code_sent(reply, blob))
    problems.extend(_ungrounded_account_claim(reply, blob))
    return problems


# A positive claim that the money is going back on the card. "cannot go back
# on the Visa" is the refusal, and the words in front of the phrase keep it.
_CARD_REFUND = (
    "refund the visa",
    "refund your visa",
    "refunded the visa",
    "refund the card",
    "back on the visa",
    "back on your visa",
    "back on the card",
    "onto the visa",
    "onto the card",
    "on the visa",
    "on your card",
    "on the card",
    "original payment",
    "visa refund",
)
_CARD_NEGATION = ("not ", "n't", "cannot", "can't", "won't", "no ")

# Carriers this desk does not call. A name is allowed only when we stored it.
_CARRIERS = ("fedex", "ups", "usps", "dhl")


def _flag_true(node: object, key: str) -> bool:
    if isinstance(node, dict):
        if node.get(key) is True:
            return True
        return any(_flag_true(value, key) for value in node.values())
    if isinstance(node, list):
        return any(_flag_true(value, key) for value in node)
    return False


def _ungrounded_card_refund(reply: str, payload: object) -> list[str]:
    """A Visa refund on a turn that may only offer store credit."""

    if not _flag_true(payload, "storeCreditOnly"):
        return []
    lowered = reply.lower()
    problems: list[str] = []
    for phrase in _CARD_REFUND:
        start = 0
        while True:
            index = lowered.find(phrase, start)
            if index < 0:
                break
            window = lowered[max(0, index - 32) : index]
            if not any(negation in window for negation in _CARD_NEGATION):
                problems.append(phrase)
                break
            start = index + len(phrase)
    return problems


_DAY_COUNT = re.compile(
    r"\b(\d{1,3})(?:\s*[–—-]\s*(\d{1,3}))?\s*(?:business\s+)?days?\b",
    re.IGNORECASE,
)
_DAY_HYPHEN = re.compile(r"\b(\d{1,3})\s*[–—-]\s*days?\b", re.IGNORECASE)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CODE_SENT = (
    "we emailed",
    "i emailed",
    "we've emailed",
    "i've emailed",
    "we sent",
    "i sent",
    "we've sent",
    "i've sent",
    "code was sent",
    "sent you a code",
    "sent a code",
    "emailed you",
    "sent you",
    "just sent",
)
_ACCOUNT_CLAIM = (
    "has an account",
    "doesn't have an account",
    "does not have an account",
    "no account",
    "account exists",
    "account does not exist",
    "is registered",
    "isn't registered",
    "is on file",
)


def _number_in_blob(number: str, blob: str) -> bool:
    return re.search(rf"(?<!\d){re.escape(number)}(?!\d)", blob) is not None


def _fact_text(node: object) -> str:
    """Payload text with the original characters, so a dash is not a JSON escape."""

    parts: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, int):
            parts.append(str(value))
            return
        if isinstance(value, str):
            parts.append(value)
            return
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
            return
        if isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return " ".join(parts).lower()


def _ungrounded_day_count(reply: str, payload: object) -> list[str]:
    """A day count whose number is not in the tool payload."""

    text = _fact_text(payload)
    problems: list[str] = []
    seen: set[str] = set()
    for pattern in (_DAY_COUNT, _DAY_HYPHEN):
        for match in pattern.finditer(reply):
            for group in match.groups():
                if not group or group in seen:
                    continue
                seen.add(group)
                if not _number_in_blob(group, text):
                    problems.append(f"{group} days")
    return problems


def _ungrounded_email(reply: str, blob: str) -> list[str]:
    """An email address the tool payload did not contain."""

    problems: list[str] = []
    for match in _EMAIL.finditer(reply):
        if match.group(0).lower() not in blob:
            problems.append(match.group(0))
    return problems


def _ungrounded_code_sent(reply: str, blob: str) -> list[str]:
    """A claim that this desk already sent a sign-in code."""

    lowered = reply.lower()
    problems: list[str] = []
    for phrase in _CODE_SENT:
        if phrase in lowered and phrase not in blob:
            problems.append(phrase)
    return problems


_CLAIM_NEGATION = ("not ", "n't", "cannot", "can't", "won't")


def _ungrounded_account_claim(reply: str, blob: str) -> list[str]:
    """A claim that an email address does or does not have an account.

    A refusal such as "does not say if an email address is on file" is not a
    claim. Saying the address is on file, with no refusal in front of it, is.
    """

    del blob
    lowered = reply.lower()
    problems: list[str] = []
    for phrase in _ACCOUNT_CLAIM:
        start = 0
        while True:
            index = lowered.find(phrase, start)
            if index < 0:
                break
            window = lowered[max(0, index - 64) : index]
            if not any(negation in window for negation in _CLAIM_NEGATION):
                problems.append(phrase)
                break
            start = index + len(phrase)
    return problems


def _ungrounded_carrier(reply: str, blob: str) -> list[str]:
    """A carrier name that was not stored on this return."""

    problems: list[str] = []
    for name in _CARRIERS:
        if re.search(rf"\b{name}\b", reply, re.IGNORECASE) and name not in blob:
            problems.append(name)
    return problems


# Longer phrases first so "out for delivery" is one status, not "delivered".
_FULFILLMENT_STATUS = (
    "out for delivery",
    "on the way",
    "packing",
    "shipped",
    "delivered",
)

# Glue in a status reply. A place or a trip sentence is not in this set.
_STATUS_DETAIL_STOP = _PLOT_STOP | {"order", "orders", "which"}


_PAST_WINDOW = re.compile(
    r"\bpast the (?:\d+-day |return )?window\b|\boutside the (?:\d+-day )?return window\b",
    re.IGNORECASE,
)
_POSITIVE_DELIVERED = re.compile(
    r"\b(?:is|was|it is|it's|it\u2019s)\s+delivered\b",
    re.IGNORECASE,
)


def _walk_dicts(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_dicts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_dicts(value)


def _payload_has_delivered_status(payload: object) -> bool:
    for node in _walk_dicts(payload):
        status = node.get("status")
        if isinstance(status, str) and status.strip().casefold() == "delivered":
            return True
    return False


def _payload_is_past_window(payload: object) -> bool:
    for node in _walk_dicts(payload):
        if node.get("window") == "past":
            return True
        mark = node.get("mark")
        if isinstance(mark, str) and "past the" in mark.casefold():
            return True
    return False


def _ungrounded_delivered_claim(reply: str, payload: object) -> list[str]:
    """A claim that the book is delivered when that status is not in the payload."""

    if _payload_has_delivered_status(payload):
        return []
    if _POSITIVE_DELIVERED.search(reply):
        return ["delivered"]
    return []


def _ungrounded_past_window(reply: str, payload: object) -> list[str]:
    """Past-window wording when this payload is not a book outside the window."""

    if _payload_is_past_window(payload):
        return []
    if _PAST_WINDOW.search(reply):
        return ["past the window"]
    return []


def _ungrounded_fulfillment_status(reply: str, blob: str) -> list[str]:
    """A shipment status in the draft that the tool payload did not contain."""

    problems: list[str] = []
    lowered = reply.lower()
    for phrase in _FULFILLMENT_STATUS:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered) and phrase not in blob:
            problems.append(phrase)
    return problems


def _ungrounded_status_detail(reply: str, payload: object, blob: str) -> list[str]:
    """Content words in a status reply that are not the stored detail.

    The check runs only when the payload carries a statusDetail, so a return
    reply is left to the other fact checks.
    """

    if not _has_key(payload, "statusDetail"):
        return []
    problems: list[str] = []
    for sentence in re.split(r"[.!?]+", reply):
        words = re.findall(r"[A-Za-z']+", sentence)
        missing = [
            word
            for word in words
            if len(word) > 2
            and word.casefold() not in _STATUS_DETAIL_STOP
            and word.casefold() not in blob
        ]
        if missing:
            problems.append(" ".join(missing))
    return problems


_OCCASION_WORD = re.compile(r"\b(gifts?|birthdays?)\b", re.IGNORECASE)


def _payload_reason(payload: object) -> str | None:
    """The customer's reason, when this phrasing payload includes one."""

    if not isinstance(payload, dict) or "reason" not in payload:
        return None
    value = payload.get("reason")
    if isinstance(value, str):
        return value
    return None


def _mentions(text: str, root: str) -> bool:
    return re.search(rf"\b{root}s?\b", text, re.IGNORECASE) is not None


def _ungrounded_occasion(reply: str, payload: object) -> list[str]:
    """Gift or birthday in a draft when the customer's reason did not say that.

    The check runs only when the phrasing payload carries a reason. A stray
    percent or code is still rejected by the fact walk above.
    """

    reason = _payload_reason(payload)
    if reason is None:
        return []
    problems: list[str] = []
    seen: set[str] = set()
    for match in _OCCASION_WORD.finditer(reply):
        token = match.group(1).lower()
        root = "gift" if token.startswith("gift") else "birthday"
        if root in seen or _mentions(reason, root):
            continue
        seen.add(root)
        problems.append(match.group(0))
    return problems


def _has_key(node: object, key: str) -> bool:
    if isinstance(node, dict):
        if key in node:
            return True
        return any(_has_key(value, key) for value in node.values())
    if isinstance(node, list):
        return any(_has_key(value, key) for value in node)
    return False


def _ungrounded_author_or_plot(reply: str, payload: object, blob: str) -> list[str]:
    """Author names and plot phrases that the tool payload did not contain."""

    problems: list[str] = []
    for match in _AUTHOR_CLAIM.finditer(reply):
        name = re.sub(r"\s+", " ", match.group(1)).strip(" .")
        if name and name.casefold() not in blob:
            problems.append(name)
    for match in _PLOT_CLAIM.finditer(reply):
        phrase = re.sub(r"\s+", " ", match.group(1)).strip(" .")
        if phrase and phrase.casefold() not in blob:
            problems.append(phrase)
    if _has_key(payload, "summary"):
        problems.extend(_summary_swap(reply, blob))
    return problems


def _summary_swap(reply: str, blob: str) -> list[str]:
    """Content words in an about-book draft that are not in the catalog summary."""

    problems: list[str] = []
    for sentence in re.split(r"[.!?]+", reply):
        words = re.findall(r"[A-Za-z']+", sentence)
        missing = [
            word
            for word in words
            if len(word) > 2 and word.casefold() not in _PLOT_STOP and word.casefold() not in blob
        ]
        if missing:
            problems.append(" ".join(missing))
    return problems


def _is_sentence_start(text: str, index: int) -> bool:
    before = text[:index].rstrip()
    return before == "" or before[-1] in ".!?"


def facts_allowed(reply: str, payload: object) -> bool:
    return not unsupported_facts(reply, payload)


_YOU_SAID = re.compile(r"\byou said\b", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def recites_prior_reason(reply: str, message: str, prior: str) -> bool:
    """True when the draft repeats last time's reason and this message does not.

    A short welcome is fine. Pasting their earlier sentence, or saying
    "you said", is not, unless those words are in what they just typed.
    """

    if _YOU_SAID.search(reply) and not _YOU_SAID.search(message or ""):
        return True
    reason_words = _words(prior or "")
    if len(reason_words) < 2:
        return False
    window = 4 if len(reason_words) >= 4 else len(reason_words)
    reply_blob = " ".join(_words(reply))
    message_blob = " ".join(_words(message or ""))
    for start in range(0, len(reason_words) - window + 1):
        phrase = " ".join(reason_words[start : start + window])
        if phrase in reply_blob and phrase not in message_blob:
            return True
    return False


def accept_draft(
    draft: str | None,
    template: str,
    payload: object,
    required: list[str],
    message: str | None = None,
    prior_reason: str | None = None,
) -> str:
    if draft is None or not draft.strip():
        return template
    text = draft.strip()
    if not facts_allowed(text, payload):
        return template
    if (
        isinstance(prior_reason, str)
        and prior_reason.strip()
        and recites_prior_reason(text, message or "", prior_reason)
    ):
        return template
    if any(item not in text for item in required):
        return template
    return text
