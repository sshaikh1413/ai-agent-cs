"""Evaluation: does Claude return the golden labels? Calls Claude; skipped without secrets.

Run with ``uv run pytest -m live tests/test_understanding_eval.py``. Each golden
sentence is labeled in the step where that label matters, then validated the
same way the machine validates it.
"""

from __future__ import annotations

import os

import pytest

from bookly_support.agent.articles import ARTICLES, normalize_article
from bookly_support.agent.understand import ClaudeUnderstander, TurnContext, offer_for, validate
from bookly_support.config import load_settings
from golden_understanding import GOLDEN

pytestmark = pytest.mark.live

_REQUIRED = ("ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "MONGODB_URI")
_PHASE_FOR = {
    "destination": "choose_destination",
    "offer_reply": "exception_offer",
    "article_id": "identify_order",
    "intents": "identify_order",
    "reason_kind": "ask_reason",
    "sentiment": "ask_reason",
}
_ARTICLES = tuple((a["id"], a["topic"]) for a in (normalize_article(dict(x)) for x in ARTICLES))

CASES = [
    (message, field, expected)
    for message, slots in GOLDEN.items()
    for field, expected in slots.items()
]


@pytest.fixture(scope="module")
def understander() -> ClaudeUnderstander:
    if any(not os.environ.get(name, "").strip() for name in _REQUIRED):
        pytest.skip("Claude secrets are not in the environment")
    return ClaudeUnderstander.from_settings(load_settings())


@pytest.mark.parametrize(("message", "field", "expected"), CASES)
def test_claude_matches_the_golden_label(understander, message, field, expected) -> None:
    phase = _PHASE_FOR[field]
    context = TurnContext(phase=phase, offer=offer_for(phase, False), articles=_ARTICLES)
    label = validate(understander.understand(message, context), context)
    assert not understander.errors, understander.errors[-1]
    if field == "intents":
        assert set(expected) <= set(label.intents), (message, label.intents)
    else:
        assert getattr(label, field) == expected, (message, field, label)
