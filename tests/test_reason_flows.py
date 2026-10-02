from bookly_support.agent.reasons import classify_reason
from bookly_support.agent.recommendations import choose_recommendation


def test_late_keywords_are_late_delivery_and_everything_else_is_other() -> None:
    assert classify_reason("It arrived late") == "late_delivery"
    assert classify_reason("There was a delay") == "late_delivery"
    assert classify_reason("It was delayed") == "late_delivery"
    assert classify_reason("It was a birthday gift") == "late_delivery"
    assert classify_reason("changed my mind") == "other"
    assert classify_reason("I can relate") == "other"


def test_recommendation_skips_horror_and_owned_titles() -> None:
    catalog = [
        {"title": "The Haunting of Hill House", "genre": "horror"},
        {"title": "Mexican Gothic", "genre": "horror"},
        {"title": "Project Hail Mary", "genre": "science fiction"},
        {"title": "Piranesi", "genre": "fantasy"},
    ]
    chosen = choose_recommendation(["Mexican Gothic", "Circe"], catalog)
    assert chosen is not None
    assert chosen["title"] == "Piranesi"
    assert choose_recommendation(["Piranesi", "Project Hail Mary"], catalog) is None
