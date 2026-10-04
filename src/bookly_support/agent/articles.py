"""Bookly's own short policy articles, and the embedding match that picks one.

The return window is not stored here. `{days}` is filled from the existing
policy document when an article is read, so there is one number only.
Example sentences are ours. They are compared as embeddings, not as a phrase
list. fastembed `bge-small-en-v1.5` is the same model that maps refund wording.
"""

from __future__ import annotations

import re
import threading

import numpy as np

from bookly_support.agent.destination import (
    CLEAR_MARGIN,
    MIN_SIMILARITY,
    shared_embedding_model,
)
from bookly_support.agent.resolve import asks_for_return, asks_order_status, asks_own_discount

# Original Bookly text. Not copied from another shop's help pages.
ARTICLES: tuple[dict, ...] = (
    {
        "id": "shipping-speed",
        "topic": "Shipping speed and price",
        "intent": "shipping",
        "body": (
            "Standard shipping takes 5\u20137 business days. "
            "It is free at $35 and over, and otherwise it is $5.99. "
            "A delivery date is not guaranteed. "
            "Business days are Monday through Friday."
        ),
        "requiredPhrase": "5\u20137 business days",
        "standardShippingCents": 599,
        "freeAtCents": 3500,
        "examples": (
            "how long does shipping take",
            "how many business days is standard shipping",
            "what does shipping cost",
            "is shipping free over a certain amount",
            "when will standard shipping arrive",
            "how much is delivery",
        ),
    },
    {
        "id": "where-we-ship",
        "topic": "Where we ship",
        "intent": "shipping",
        "body": "Bookly ships to United States addresses only.",
        "requiredPhrase": "United States addresses only",
        "examples": (
            "where do you ship",
            "do you ship outside the united states",
            "do you ship to canada",
            "which countries do you deliver to",
            "do you only ship in the us",
        ),
    },
    {
        "id": "tracking",
        "topic": "Tracking",
        "intent": "shipping",
        "body": (
            "Bookly emails a status when an order ships. "
            "For an order on your account, ask where it is and this desk reads the status stored on that order."
        ),
        "requiredPhrase": "emails a status when an order ships",
        "examples": (
            "how do I track a package",
            "do you send a tracking email",
            "how will I know when it ships",
            "do you email when an order ships",
            "where do I find tracking",
        ),
    },
    {
        "id": "returns",
        "topic": "Returns",
        "intent": "policy",
        "usesReturnWindow": True,
        "body": (
            "A delivered book can be returned within {days} days of delivery. "
            "The refund goes to the original payment. "
            "When that window has closed, the one-time store credit on this desk is the refund, "
            "and the label is the parcel label this desk writes."
        ),
        "requiredPhrase": "{days} days of delivery",
        "examples": (
            "what is your return policy",
            "how many days do I have to return a book",
            "how long is the return window",
            "can I return a book for a refund",
            "what is the return window",
        ),
    },
    {
        "id": "refund-timing",
        "topic": "Refund timing",
        "intent": "policy",
        "body": (
            "Store credit shows on the receipt right away. "
            "A card refund can take several business days to appear on the statement."
        ),
        "requiredPhrase": "several business days",
        "examples": (
            "how long does a refund take",
            "when will the money show on my card",
            "when does store credit appear",
            "how long until a card refund posts",
            "when will I see the refund",
        ),
    },
    {
        "id": "cancel",
        "topic": "Cancel an order",
        "intent": "policy",
        "body": (
            "Bookly can cancel an order only while its status is packing. "
            "This is the rule. This desk does not cancel the order."
        ),
        "requiredPhrase": "only while its status is packing",
        "examples": (
            "can I cancel my order",
            "how do I cancel an order",
            "please cancel this order",
            "is it too late to cancel",
            "I want to cancel my order",
        ),
    },
    {
        "id": "address-change",
        "topic": "Change an address",
        "intent": "policy",
        "body": (
            "Bookly can change a shipping address only while the status is packing. "
            "This is the rule. This desk does not change the address."
        ),
        "requiredPhrase": "does not change the address",
        "examples": (
            "can I change my shipping address",
            "I need to update the delivery address",
            "change my address",
            "can you edit the ship-to address",
            "I put the wrong address on the order",
        ),
    },
    {
        "id": "damaged-or-wrong",
        "topic": "Damaged or wrong book",
        "intent": "policy",
        "body": (
            "If a book arrives damaged, or it is the wrong book, "
            "start a return and say that in the reason."
        ),
        "requiredPhrase": "say that in the reason",
        "examples": (
            "my book arrived damaged",
            "I got the wrong book",
            "the book is damaged",
            "you sent the wrong title",
            "what if the book arrives broken",
        ),
    },
    {
        "id": "gift-order",
        "topic": "Gift order",
        "intent": "policy",
        "body": (
            "A gift can be returned without the price being told to the recipient. "
            "Bookly does not keep a separate gift receipt. "
            "This desk looks up the order on the buyer's account."
        ),
        "requiredPhrase": "buyer's account",
        "examples": (
            "can I return a gift",
            "this was a gift",
            "return a gift without showing the price",
            "do you have a gift receipt",
            "the recipient does not know the price",
        ),
    },
    {
        "id": "sign-in",
        "topic": "Sign-in",
        "intent": "password_reset",
        "body": (
            "Bookly emails a one-time code for sign-in. "
            "This desk does not send that code, does not ask you to type a password, "
            "and does not say if an email address is on file."
        ),
        "requiredPhrase": "does not send that code",
        "examples": (
            "I forgot my password",
            "I can't sign in",
            "I am locked out",
            "how do I log in",
            "I didn't get a sign-in code",
            "reset my password",
        ),
    },
    {
        "id": "discount-code",
        "topic": "Discount code at checkout",
        "intent": "policy",
        "body": (
            "At checkout, enter the code in the discount box before you pay. "
            "If a code is on your account, ask for your discount code and this desk reads it from your discounts."
        ),
        "requiredPhrase": "discount box",
        "examples": (
            "how do I enter a discount code",
            "where do I put a promo code at checkout",
            "how does a coupon work",
            "where is the discount box",
            "how do I use a code when I pay",
        ),
    },
    {
        "id": "what-we-sell",
        "topic": "What we sell",
        "intent": "policy",
        "body": "Bookly sells physical books. This shop does not sell ebooks, audiobooks, or magazines.",
        "requiredPhrase": "physical books",
        "examples": (
            "do you sell ebooks",
            "do you have audiobooks",
            "what do you sell",
            "do you sell magazines",
            "are the books physical",
        ),
    },
    {
        "id": "confirmation-email",
        "topic": "Missing confirmation email",
        "intent": "policy",
        "body": (
            "If the order confirmation is missing, check the spam folder. "
            "The order is still on the account when it shows in your recent orders."
        ),
        "requiredPhrase": "check the spam folder",
        "examples": (
            "I didn't get an order confirmation email",
            "the confirmation email is missing",
            "check spam for the order email",
            "no confirmation email",
            "where is my order confirmation",
        ),
    },
    {
        "id": "sales-tax",
        "topic": "Sales tax",
        "intent": "policy",
        "body": (
            "Sales tax is charged for the ship-to state and is included in the order total already stored. "
            "This desk does not state a tax rate."
        ),
        "requiredPhrase": "does not state a tax rate",
        "examples": (
            "do you charge sales tax",
            "is tax included in the total",
            "how is sales tax calculated",
            "which state is the tax based on",
            "what is the tax rate",
        ),
    },
)

_CUE = re.compile(
    r"\b(?:polic(?:y|ies)|how long|how many|shipping|password|sign[- ]?in|"
    r"log ?in|login|discount|promo|coupon|ebooks?|audiobooks?|magazines?|"
    r"sales tax|\btax\b|cancel|address|damaged|wrong book|gift|tracking|"
    r"confirmation|spam|what do you sell|physical books)\b",
    re.IGNORECASE,
)

_lock = threading.Lock()
_cached_key: tuple[str, ...] | None = None
_cached_labels: tuple[str, ...] | None = None
_cached_matrix: np.ndarray | None = None


def article_document(article: dict) -> dict:
    """The Atlas shape. The return-window number is not copied onto the article."""

    if article.get("usesReturnWindow") and re.search(r"\d", article["body"]):
        raise ValueError("The returns article must not store its own day count.")
    document = {
        "_id": article["id"],
        "kind": "article",
        "topic": article["topic"],
        "intent": article["intent"],
        "body": article["body"],
        "requiredPhrase": article["requiredPhrase"],
        "examples": list(article["examples"]),
        "usesReturnWindow": bool(article.get("usesReturnWindow")),
    }
    if "standardShippingCents" in article:
        document["standardShippingCents"] = int(article["standardShippingCents"])
    if "freeAtCents" in article:
        document["freeAtCents"] = int(article["freeAtCents"])
    return document


def normalize_article(document: dict) -> dict:
    """A stored article, or one of the in-code articles, in one shape."""

    article_id = document.get("id") or document.get("_id")
    examples = document.get("examples") or ()
    normalized = {
        "id": str(article_id),
        "topic": str(document.get("topic") or ""),
        "intent": str(document.get("intent") or "policy"),
        "body": str(document.get("body") or ""),
        "requiredPhrase": str(document.get("requiredPhrase") or ""),
        "examples": tuple(str(item) for item in examples),
        "usesReturnWindow": bool(document.get("usesReturnWindow")),
    }
    if document.get("standardShippingCents") is not None:
        normalized["standardShippingCents"] = int(document["standardShippingCents"])
    if document.get("freeAtCents") is not None:
        normalized["freeAtCents"] = int(document["freeAtCents"])
    return normalized


def public_article(article: dict, return_window_days: int) -> dict:
    """One article for the tool payload. Examples stay off this dict.

    When the article uses the return window, the only day count is
    `return_window_days` from the existing policy document.
    """

    source = normalize_article(article)
    if source["usesReturnWindow"] and re.search(r"\d", source["body"]):
        raise ValueError("The returns article must not store its own day count.")
    if source["usesReturnWindow"]:
        if return_window_days < 1:
            body = "The return window is not on file, so I can't say how many days."
            phrase = "not on file"
            days_field = None
        else:
            days = str(return_window_days)
            body = source["body"].replace("{days}", days)
            phrase = source["requiredPhrase"].replace("{days}", days)
            days_field = return_window_days
    else:
        body = source["body"]
        phrase = source["requiredPhrase"]
        days_field = None
    payload = {
        "id": source["id"],
        "topic": source["topic"],
        "intent": source["intent"],
        "body": body,
        "requiredPhrase": phrase,
    }
    if days_field is not None:
        payload["returnWindowDays"] = days_field
    if "standardShippingCents" in source:
        payload["standardShippingCents"] = source["standardShippingCents"]
    if "freeAtCents" in source:
        payload["freeAtCents"] = source["freeAtCents"]
    return payload


def article_named(text: str, articles: list[dict]) -> str | None:
    """An article id or topic typed or clicked, or None."""

    cleaned = re.sub(r"\s+", " ", text).strip().casefold().strip(" \t.!?")
    if not cleaned:
        return None
    for article in articles:
        item = normalize_article(article)
        if cleaned == item["id"].casefold() or cleaned == item["topic"].casefold():
            return item["id"]
    return None


def is_policy_question(text: str) -> bool:
    """A general shop question. A return she is starting is not one of these.

    A cue is required. "Why not" and "what are your store hours" stay on the
    return desk instead of opening the topic list.
    """

    if asks_order_status(text) or asks_own_discount(text):
        return False
    if _CUE.search(text) is None:
        return False
    if asks_for_return(text) and not re.search(
        r"\b(?:polic(?:y|ies)|how long|how many|window)\b",
        text,
        re.IGNORECASE,
    ):
        return False
    return True


def match_article(text: str, articles: list[dict]) -> str | None:
    """The article id when one set of examples is clearly ahead, or None."""

    cleaned = text.strip()
    rows = [normalize_article(article) for article in articles if article.get("examples")]
    if not cleaned or not rows:
        return None
    model = shared_embedding_model()
    labels, matrix = _example_matrix(model, rows)
    query = _unit(np.stack(list(model.embed([cleaned]))))
    scores = matrix @ query[0]
    best: dict[str, float] = {}
    for label, score in zip(labels, scores, strict=True):
        value = float(score)
        if label not in best or value > best[label]:
            best[label] = value
    if not best:
        return None
    ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)
    winner_id, winner = ranked[0]
    other = ranked[1][1] if len(ranked) > 1 else 0.0
    if winner < MIN_SIMILARITY or winner - other < CLEAR_MARGIN:
        return None
    return winner_id


def _example_matrix(model, articles: list[dict]) -> tuple[tuple[str, ...], np.ndarray]:
    global _cached_key, _cached_labels, _cached_matrix
    labels: list[str] = []
    texts: list[str] = []
    for article in articles:
        for example in article["examples"]:
            labels.append(article["id"])
            texts.append(example)
    key = tuple(texts)
    if _cached_key == key and _cached_labels is not None and _cached_matrix is not None:
        return _cached_labels, _cached_matrix
    with _lock:
        if _cached_key == key and _cached_labels is not None and _cached_matrix is not None:
            return _cached_labels, _cached_matrix
        matrix = _unit(np.stack(list(model.embed(texts))))
        _cached_key = key
        _cached_labels = tuple(labels)
        _cached_matrix = matrix
        return _cached_labels, matrix


def _unit(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.clip(norms, 1e-12, None)
