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


# What the reason is about, so Mara can acknowledge it in her own words instead of
# repeating the sentence. Claude labels this in ``understand``; these keywords are the
# fallback. Order matters: a damaged book that was also boring is about the damage.
_TOPICS = (
    ("late", _LATE_REASON),
    ("damaged", re.compile(r"\b(?:damaged|torn|ripped|bent|broken|crushed|wet|water|stain(?:ed)?|missing pages?|cracked|scratched|falling apart)\b", re.IGNORECASE)),
    ("wrong_book", re.compile(r"\b(?:wrong (?:book|title|edition|one|item)|not what i ordered|different (?:book|edition)|sent me the wrong)\b", re.IGNORECASE)),
    ("duplicate", re.compile(r"\b(?:already (?:have|own|had|read)|duplicate|ordered (?:it )?twice|two copies|got (?:it )?twice|bought it twice)\b", re.IGNORECASE)),
    ("changed_mind", re.compile(r"\b(?:changed my mind|don'?t need|no longer need|not needed|by mistake|accident(?:ally)?|ordered (?:it )?by accident)\b", re.IGNORECASE)),
    ("not_for_me", re.compile(r"\b(?:boring|bored|didn'?t (?:like|love|enjoy|get into)|did not (?:like|enjoy)|not (?:for me|my (?:thing|style|taste|genre|type))|genre|hated?|dull|slow|couldn'?t get into|not (?:good|great|interesting)|disappointing|disappointed|meh|too (?:long|slow|dark|sad))\b", re.IGNORECASE)),
)
REASON_TOPICS = ("late", "damaged", "wrong_book", "duplicate", "changed_mind", "not_for_me", "other")


def reason_topic(text: str) -> str:
    """late, damaged, wrong_book, duplicate, changed_mind, not_for_me, or other."""

    for topic, pattern in _TOPICS:
        if pattern.search(text or ""):
            return topic
    return "other"
