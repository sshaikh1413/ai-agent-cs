"""The evaluation set: what Claude should label for the sentences the desk must handle.

These used to be embedding examples and a sentiment lexicon in the request path.
Now they are expectations. The pure tests use ``GoldenUnderstander`` so the state
machine is tested against these labels without calling Claude, and
``test_understanding_eval.py`` (marked live) sends the same sentences to Claude
and checks that it returns them.

Keys are lowercased and stripped. Values only list the slots that matter for
that sentence; ``validate`` drops any slot the current step did not ask for.
"""

from __future__ import annotations

from bookly_support.agent.understand import RuleUnderstander, TurnContext, Understanding

ORIGINAL = {"destination": "original_payment", "offer_reply": "refuse"}
STORE = {"destination": "store_credit", "offer_reply": "accept"}
ACCEPT = {"offer_reply": "accept"}
REFUSE = {"offer_reply": "refuse"}
UNSURE = {"offer_reply": "unsure"}
NOTHING: dict = {}

GOLDEN: dict[str, dict] = {
    # Refund destination wording that is not a closed phrase.
    "card is fine": ORIGINAL,
    "visa is fine": ORIGINAL,
    "the card works": ORIGINAL,
    "put it back on the card": ORIGINAL,
    "can i get it on my visa instead?": ORIGINAL,
    "store credit is fine": STORE,
    "credit on my account": STORE,
    "blue": NOTHING,
    "whatever": UNSURE,
    # Yes and no to the one-time store-credit exception.
    "yeah that'd be great": ACCEPT,
    "yeah that would be great": ACCEPT,
    "that works": ACCEPT,
    "sounds good": ACCEPT,
    "sure": ACCEPT,
    "yes": ACCEPT,
    "i'll take it": ACCEPT,
    "i will take it": ACCEPT,
    "no": REFUSE,
    "no thanks": REFUSE,
    "never mind": REFUSE,
    "why not": UNSURE,
    "i guess": UNSURE,
    "the weather is nice today": NOTHING,
    # One policy article, chosen from the listed ids.
    "how long does shipping take?": {"intents": ["policy_question"], "article_id": "shipping-speed"},
    "how do i enter a discount code?": {"intents": ["policy_question"], "article_id": "discount-code"},
    "can i cancel my order?": {"intents": ["policy_question"], "article_id": "cancel"},
    "can i change my shipping address?": {"intents": ["policy_question"], "article_id": "address-change"},
    "shipping and tax": {"intents": ["policy_question"], "article_id": None},
    # The reason they typed: kind and tone.
    "this book was awful and i hated every page.": {"reason_kind": "other", "sentiment": "negative"},
    "i loved this wonderful book and it made me so happy!": {"reason_kind": "other", "sentiment": "positive"},
    "changed my mind": {"reason_kind": "other", "sentiment": "neutral"},
    # VADER scored this one positive. A disappointed reader is not positive.
    "it wasn't scary at all": {"reason_kind": "other", "sentiment": "negative"},
    "it arrived late": {"reason_kind": "late_delivery", "sentiment": "neutral"},
    "this awful late delivery ruined everything and i hated it": {
        "reason_kind": "late_delivery",
        "sentiment": "negative",
    },
}


def key(message: str) -> str:
    return " ".join(message.split()).strip().lower().replace("\u2019", "'")


class GoldenUnderstander:
    """Rules for the intents, plus the golden slots for sentences in the set."""

    def __init__(self) -> None:
        self._rules = RuleUnderstander()

    def understand(self, message: str, context: TurnContext) -> Understanding:
        base = self._rules.understand(message, context)
        golden = GOLDEN.get(key(message))
        if golden is None:
            return base
        fields = base.model_dump()
        for name, value in golden.items():
            if name == "intents":
                fields["intents"] = list(dict.fromkeys([*fields["intents"], *value]))
            else:
                fields[name] = value
        return Understanding(**fields)
