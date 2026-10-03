"""Label a return reason. Genre comes from the order, not from this text."""

from __future__ import annotations

import re

_LATE_REASON = re.compile(r"\b(?:late|delay(?:ed)?|birthday|gift)\b", re.IGNORECASE)


def classify_reason(text: str) -> str:
    """Keyword hits for late, delay, birthday, or gift become late_delivery.

    Anything else stays other. Word boundaries keep "relate" from matching "late".
    """

    if _LATE_REASON.search(text or ""):
        return "late_delivery"
    return "other"
