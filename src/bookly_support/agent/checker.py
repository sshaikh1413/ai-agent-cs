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


def _walk(node: object, cents: set[int], dates: set[date], strings: list[str]) -> None:
    if isinstance(node, bool) or node is None:
        return
    if isinstance(node, int):
        cents.add(node)
        return
    if isinstance(node, str):
        strings.append(node)
        if re.fullmatch(r"\d+\.\d{2}", node):
            dollars, fraction = node.split(".")
            cents.add(int(dollars) * 100 + int(fraction))
        for match in _ISO_DATE.finditer(node):
            dates.add(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        return
    if isinstance(node, dict):
        for value in node.values():
            _walk(value, cents, dates, strings)
        return
    if isinstance(node, list):
        for value in node:
            _walk(value, cents, dates, strings)


def _payload_facts(payload: object) -> tuple[str, set[int], set[date]]:
    cents: set[int] = set()
    dates: set[date] = set()
    strings: list[str] = []
    _walk(payload, cents, dates, strings)
    blob = json.dumps(payload, default=str).lower()
    return blob, cents, dates


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

    blob, cents, dates = _payload_facts(payload)
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

    lowered = reply.lower()
    if any(phrase in lowered for phrase in _COMPLETION_CLAIM) or (
        "receipt" in lowered and "rcpt_" in lowered
    ):
        if not completion_is_grounded(payload):
            problems.append("completion")

    return problems


def facts_allowed(reply: str, payload: object) -> bool:
    return not unsupported_facts(reply, payload)


def accept_draft(draft: str | None, template: str, payload: object, required: list[str]) -> str:
    if draft is None or not draft.strip():
        return template
    text = draft.strip()
    if not facts_allowed(text, payload):
        return template
    if any(item not in text for item in required):
        return template
    return text
