"""Author and summary follow-ups. No Claude and no Atlas."""

from datetime import date

from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.recommendations import choose_recommendation

from test_allowlist import NOW, TODAY, FakeStore, _CATALOG, _order

PIRANESI = "A man records the tides in a house of statues."


def _done_session() -> tuple[FakeStore, Session, Machine]:
    store = FakeStore(
        [_order("BLY-22044", "Mexican Gothic", date(2026, 9, 30), date(2026, 10, 1), 1699, "horror")],
        catalog=_CATALOG,
    )
    session = Session(
        id="conv_about",
        customer_id="cust_becky",
        phase="done",
        order_id="BLY-22044",
        title="Mexican Gothic",
        genre="horror",
    )
    return store, session, Machine(store)


def test_author_follow_up_uses_the_recommended_title() -> None:
    store, session, machine = _done_session()
    offered = machine.step(session, "do you recommend any books for me?", today=TODAY, now=NOW)
    expected = choose_recommendation(["Mexican Gothic"], _CATALOG, "BLY-22044")
    assert expected is not None
    assert expected["title"] == "Piranesi"
    assert offered.template == "Piranesi"
    assert PIRANESI not in offered.template
    assert "Susanna Clarke" not in offered.template
    assert session.recommended_title == "Piranesi"

    turn = machine.step(session, "who is the author?", today=TODAY, now=NOW)
    assert turn.step == "Step: about this book"
    assert [tool.name for tool in turn.tools] == ["lookup_catalog"]
    assert turn.tools[0].payload["title"] == "Piranesi"
    assert turn.tools[0].payload["author"] == "Susanna Clarke"
    assert turn.tools[0].payload["summary"] == PIRANESI
    assert turn.template == "Piranesi is by Susanna Clarke."
    assert PIRANESI not in turn.template
    assert "Silvia Moreno-Garcia" not in turn.template
    assert session.phase == "done"


def test_what_is_it_about_returns_the_stored_summary() -> None:
    store, session, machine = _done_session()
    machine.step(session, "do you recommend any books?", today=TODAY, now=NOW)
    for question in ("what is it about?", "what is the book about?"):
        turn = machine.step(session, question, today=TODAY, now=NOW)
        assert turn.step == "Step: about this book"
        assert turn.tools[0].payload["title"] == "Piranesi"
        assert turn.template == PIRANESI
        assert "Susanna Clarke" not in turn.template
        assert "Silvia Moreno-Garcia" not in turn.template
    assert store.calls.count("lookup_catalog") == 2


def test_without_a_recommendation_the_order_title_is_used() -> None:
    store = FakeStore(
        [_order("BLY-22002", "Circe", date(2026, 9, 11), date(2026, 9, 15), 1700, "fiction")],
        catalog=[
            {
                "title": "Circe",
                "genre": "fiction",
                "author": "Madeline Miller",
                "summary": "A nymph exiled to an island learns witchcraft and outlasts the gods who land there.",
            }
        ],
    )
    session = Session(
        id="conv_order",
        customer_id="cust_becky",
        phase="ask_reason",
        order_id="BLY-22002",
        title="Circe",
        genre="fiction",
    )
    turn = Machine(store).step(session, "who is the author?", today=TODAY, now=NOW)
    assert session.recommended_title is None
    assert session.phase == "ask_reason"
    assert session.reason is None
    assert turn.tools[0].payload["title"] == "Circe"
    assert turn.template == "Circe is by Madeline Miller."
    assert turn.step == "Step: about this book"


def test_missing_catalog_row_does_not_invent_an_author() -> None:
    store = FakeStore(
        [_order("BLY-22002", "Circe", date(2026, 9, 11), date(2026, 9, 15), 1700, "fiction")],
        catalog=[],
    )
    session = Session(
        id="conv_missing",
        customer_id="cust_becky",
        phase="ask_reason",
        order_id="BLY-22002",
        title="Circe",
        genre="fiction",
    )
    turn = Machine(store).step(session, "who is the author?", today=TODAY, now=NOW)
    assert turn.tools[0].payload == {"title": "Circe", "author": None, "summary": None}
    assert turn.template == "I don't have that on file."
    assert "Miller" not in turn.template
    assert "witch" not in turn.template.lower()
    assert "Circe" not in turn.template
    about = Machine(store).step(session, "what is it about?", today=TODAY, now=NOW)
    assert about.template == "I don't have that on file."
    assert about.tools[0].payload["summary"] is None
    assert "island" not in about.template
