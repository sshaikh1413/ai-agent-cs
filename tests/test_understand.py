"""Claude labels; code decides. No Claude and no Atlas."""

from __future__ import annotations

import json

from pydantic_ai.models.test import TestModel
from pydantic_ai.profiles import ModelProfile

from bookly_support.agent.understand import (
    ClaudeUnderstander,
    RuleUnderstander,
    TurnContext,
    Understanding,
    validate,
)
from bookly_support.config import Settings

ARTICLES = (("shipping-speed", "Shipping speed and price"), ("cancel", "Cancel an order"))


def test_an_article_id_that_is_not_listed_is_dropped() -> None:
    context = TurnContext(phase="identify_order", articles=ARTICLES)
    made_up = Understanding(intents=["policy_question"], article_id="free-shipping-forever")
    assert validate(made_up, context).article_id is None
    listed = Understanding(intents=["policy_question"], article_id="cancel")
    assert validate(listed, context).article_id == "cancel"


def test_a_destination_counts_only_while_mara_is_asking_for_one() -> None:
    label = Understanding(intents=[], destination="store_credit")
    assert validate(label, TurnContext(phase="choose_destination")).destination == "store_credit"
    assert validate(label, TurnContext(phase="identify_order")).destination is None
    assert validate(label, TurnContext(phase="exception_offer")).destination is None


def test_low_confidence_drops_anything_that_would_write() -> None:
    shaky = Understanding(intents=["other"], destination="original_payment", confidence=0.3)
    assert validate(shaky, TurnContext(phase="choose_destination")).destination is None
    unsure = Understanding(intents=[], offer_reply="accept", confidence=0.3)
    assert validate(unsure, TurnContext(phase="exception_offer")).offer_reply == "unsure"


def test_other_is_not_an_intent_the_machine_sees() -> None:
    label = validate(Understanding(intents=["other", "order_status", "order_status"]), TurnContext(phase="done"))
    assert label.intents == ["order_status"]


def test_claude_output_is_parsed_into_the_schema() -> None:
    # Native structured output: Claude answers with JSON text, not a tool call.
    model = TestModel(
        custom_output_text=json.dumps(
            {
                "intents": ["policy_question"],
                "article_id": "cancel",
                "confidence": 0.9,
            }
        ),
        profile=ModelProfile(supports_json_schema_output=True),
    )
    understander = ClaudeUnderstander.from_settings(Settings("key", "ws", "uri"), model=model)
    label = understander.understand("can I cancel?", TurnContext(phase="identify_order", articles=ARTICLES))
    assert label.intents == ["policy_question"]
    assert label.article_id == "cancel"
    assert understander.calls == 1
    assert understander.errors == []


def test_a_failed_call_falls_back_to_the_rules() -> None:
    class _Broken:
        def run_sync(self, prompt: str):
            raise RuntimeError("upstream timeout sk-ant-secret123")

    understander = ClaudeUnderstander(agent=_Broken(), fallback=RuleUnderstander())
    label = understander.understand("where is my order", TurnContext(phase="identify_order"))
    assert "order_status" in label.intents
    assert understander.errors and "sk-ant-redacted" in understander.errors[0]
