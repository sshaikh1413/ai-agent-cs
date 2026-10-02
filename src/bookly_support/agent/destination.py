"""Map an unmatched refund sentence to a destination we already listed.

fastembed embeds the customer message and a short list of example sentences
for original payment and for store credit. The closer label is used only when
it is clearly ahead of the other. Claude is not asked to choose.
"""

from __future__ import annotations

import threading

import numpy as np
from fastembed import TextEmbedding

MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Best cosine to the winning label must clear this, and must beat the other
# label by at least CLEAR_MARGIN. Otherwise the desk asks again.
MIN_SIMILARITY = 0.80
CLEAR_MARGIN = 0.12

# Example sentences we own. They are compared as embeddings, not as a phrase list.
ORIGINAL_EXAMPLES = (
    "card is fine",
    "visa is fine",
    "the card works",
    "put it back on the card",
    "refund it to the card I paid with",
    "the original payment method",
    "back on my visa",
)
STORE_EXAMPLES = (
    "store credit is fine",
    "credit on my account",
    "give me store credit",
    "put the refund on my account as credit",
    "shop credit please",
)

_LABELS = ("original_payment",) * len(ORIGINAL_EXAMPLES) + ("store_credit",) * len(STORE_EXAMPLES)
_TEXTS = ORIGINAL_EXAMPLES + STORE_EXAMPLES

_lock = threading.Lock()
_model: TextEmbedding | None = None
_examples: np.ndarray | None = None


def closest_destination(text: str) -> str | None:
    """The destination whose examples are clearly closer, or None."""

    cleaned = text.strip()
    if not cleaned:
        return None
    model, examples = _ready()
    query = _unit(np.stack(list(model.embed([cleaned]))))
    scores = examples @ query[0]
    best: dict[str, float] = {}
    for label, score in zip(_LABELS, scores, strict=True):
        value = float(score)
        if label not in best or value > best[label]:
            best[label] = value
    original = best["original_payment"]
    store = best["store_credit"]
    if original >= store:
        winner, other, label = original, store, "original_payment"
    else:
        winner, other, label = store, original, "store_credit"
    if winner < MIN_SIMILARITY or winner - other < CLEAR_MARGIN:
        return None
    return label


def _ready() -> tuple[TextEmbedding, np.ndarray]:
    global _model, _examples
    if _model is not None and _examples is not None:
        return _model, _examples
    with _lock:
        if _model is None or _examples is None:
            model = TextEmbedding(model_name=MODEL_NAME)
            _examples = _unit(np.stack(list(model.embed(list(_TEXTS)))))
            _model = model
        return _model, _examples


def _unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.clip(norms, 1e-12, None)
