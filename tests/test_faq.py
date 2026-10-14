"""Typing FAQ lists the questions people ask most. No Claude and no Atlas."""

from bookly_support.agent.articles import ARTICLES, FAQ, faq_page, faq_pick
from bookly_support.agent.checker import unsupported_facts

from test_policy_articles import NOW, TODAY, _desk


def test_faq_lists_the_top_five_and_a_show_more_button() -> None:
    store, machine, session = _desk()
    for phrase in ("FAQ", "faq", "FAQs", "show me the faq", "frequently asked questions"):
        turn = machine.step(session, phrase, today=TODAY, now=NOW)
        assert turn.step == "Step: FAQ", phrase
        assert len(turn.choices) == 6, phrase
        assert [c.title for c in turn.choices[:5]] == [item["question"] for item in FAQ[:5]]
        assert [c.order_id for c in turn.choices[:5]] == [f"faq:{item['articleId']}" for item in FAQ[:5]]
        assert turn.choices[5].title == "Show more questions"
        assert turn.choices[5].order_id == "faq:more:5"
        assert turn.choices[5].mark == f"{len(FAQ) - 5} more"
        assert session.phase == "identify_order", phrase
    assert "get_policy_article" not in store.calls


def test_show_more_pages_through_every_question_then_stops() -> None:
    _store, machine, session = _desk()
    seen: list[str] = []
    turn = machine.step(session, "FAQ", today=TODAY, now=NOW)
    while True:
        seen += [c.order_id for c in turn.choices if not c.order_id.startswith("faq:more:")]
        more = [c for c in turn.choices if c.order_id.startswith("faq:more:")]
        if not more:
            break
        turn = machine.step(session, more[0].order_id, today=TODAY, now=NOW)
        assert turn.step == "Step: FAQ"
        assert "more questions" in turn.template
    assert seen == [f"faq:{item['articleId']}" for item in FAQ]
    assert len(FAQ) == len(ARTICLES)


def test_clicking_a_question_answers_from_its_article() -> None:
    store, machine, session = _desk()
    machine.step(session, "FAQ", today=TODAY, now=NOW)
    turn = machine.step(session, "faq:returns", today=TODAY, now=NOW)
    assert turn.step == "Step: policy"
    assert store.calls.count("get_policy_article") == 1
    assert turn.tools[0].payload["id"] == "returns"
    assert "30 days of delivery" in turn.template
    assert unsupported_facts(turn.template, turn.payload) == []
    assert session.phase == "identify_order"
    assert "start_return" not in store.calls


def test_faq_mid_return_keeps_the_return_where_it_was() -> None:
    store, machine, session = _desk()
    machine.step(session, "I want to return The Midnight Library", today=TODAY, now=NOW)
    phase = session.phase
    order_id = session.order_id
    listed = machine.step(session, "FAQ", today=TODAY, now=NOW)
    assert listed.step == "Step: FAQ"
    answered = machine.step(session, "faq:refund-timing", today=TODAY, now=NOW)
    assert answered.tools[0].payload["id"] == "refund-timing"
    assert session.phase == phase
    assert session.order_id == order_id
    assert "start_return" not in store.calls


def test_typed_returns_is_not_a_faq_click() -> None:
    assert faq_pick("returns") is None
    assert faq_pick("faq:returns") == "returns"
    assert faq_pick("faq:not-an-article") is None
    assert faq_pick("faq:more:5") is None
    assert faq_page("faq:more:5") == 5
    assert faq_page("faq:more:999") is None
    assert faq_page("faq:returns") is None
    assert faq_page("where is my order") is None
