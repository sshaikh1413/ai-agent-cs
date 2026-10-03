from bookly_support.agent.reasons import classify_reason
from bookly_support.agent.recommendations import choose_recommendation
from bookly_support.agent.sentiment import label_sentiment


def test_late_keywords_are_late_delivery_and_everything_else_is_other() -> None:
    assert classify_reason("It arrived late") == "late_delivery"
    assert classify_reason("There was a delay") == "late_delivery"
    assert classify_reason("It was delayed") == "late_delivery"
    assert classify_reason("It was a birthday gift") == "late_delivery"
    assert classify_reason("changed my mind") == "other"
    assert classify_reason("I can relate") == "other"


def test_catalog_pick_is_stable_for_an_order_and_skips_horror_and_owned() -> None:
    catalog = [
        {"title": "The Haunting of Hill House", "genre": "horror"},
        {"title": "Mexican Gothic", "genre": "horror"},
        {"title": "The Shining", "genre": "Horror"},
        {"title": "Project Hail Mary", "genre": "science fiction"},
        {"title": "Piranesi", "genre": "fantasy"},
        {"title": "Circe", "genre": "fiction"},
        {"title": "Dune", "genre": "science fiction"},
        {"title": "Educated", "genre": "memoir"},
    ]
    owned = ["Mexican Gothic"]
    first = choose_recommendation(owned, catalog, "BLY-22044")
    again = choose_recommendation(owned, catalog, "BLY-22044")
    assert first == again
    assert first is not None
    assert first["title"] not in {"The Haunting of Hill House", "Mexican Gothic", "The Shining"}
    assert first["genre"].casefold() != "horror"
    blocked = choose_recommendation([*owned, first["title"]], catalog, "BLY-22044")
    assert blocked is None or blocked["title"] != first["title"]
    assert choose_recommendation(
        ["Piranesi", "Project Hail Mary", "Circe", "Dune", "Educated"],
        catalog,
        "BLY-22044",
    ) is None
    picks = {
        choose_recommendation([], catalog, f"BLY-{number}")["title"]
        for number in range(40)
    }
    assert len(picks) > 1


def test_sentiment_labels_a_negative_sentence_and_a_positive_one() -> None:
    assert label_sentiment("This book was awful and I hated every page.") == "negative"
    assert label_sentiment("I loved this wonderful book and it made me so happy!") == "positive"
    assert label_sentiment("changed my mind") == "neutral"
