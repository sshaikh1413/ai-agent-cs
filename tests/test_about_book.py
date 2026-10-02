"""Author and summary follow-ups. No Claude and no Atlas."""

from datetime import date

from bookly_support.agent.checker import accept_draft
from bookly_support.agent.machine import Machine, Session
from bookly_support.agent.recommendations import choose_recommendation
from bookly_support.agent.resolve import book_question

from test_allowlist import NOW, TODAY, FakeStore, _CATALOG, _order

PIRANESI = "A man records the tides in a house of statues."
BECOMING = (
    "Michelle Obama recounts Chicago, her law career, "
    "and the years her family lived in the White House."
)


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


def test_named_title_answers_author_and_what_the_book_is_about() -> None:
    store, session, machine = _done_session()
    offered = machine.step(session, "do you recommend any books for me?", today=TODAY, now=NOW)
    assert offered.template == "Piranesi"
    assert session.recommended_title == "Piranesi"
    store.catalog.append(
        {
            "title": "Becoming",
            "genre": "memoir",
            "author": "Michelle Obama",
            "summary": BECOMING,
        }
    )
    question = "what's Becoming about and who is the author"
    assert book_question("author") == "author"
    assert book_question("who wrote Becoming") == "author"
    assert book_question("what's Becoming about") == "summary"
    assert book_question(question) == "both"

    turn = machine.step(session, question, today=TODAY, now=NOW)
    assert turn.step == "Step: about this book"
    assert [tool.name for tool in turn.tools] == ["lookup_catalog"]
    assert turn.tools[0].payload["title"] == "Becoming"
    assert turn.tools[0].payload["author"] == "Michelle Obama"
    assert turn.tools[0].payload["summary"] == BECOMING
    assert turn.template == f"Becoming is by Michelle Obama. {BECOMING}"
    assert "Piranesi" not in turn.template
    assert "Susanna Clarke" not in turn.template
    assert "anything else" not in turn.template.lower()
    assert session.phase == "done"
    assert session.recommended_title == "Piranesi"
    swapped = turn.template.replace("Michelle Obama", "Tara Westover", 1)
    assert "Tara Westover" in swapped
    assert accept_draft(swapped, turn.template, turn.payload, turn.required) == turn.template

    wrote = machine.step(session, "who wrote Becoming", today=TODAY, now=NOW)
    assert wrote.tools[0].payload["title"] == "Becoming"
    assert wrote.template == "Becoming is by Michelle Obama."
    assert wrote.template != BECOMING

    about = machine.step(session, "what's Becoming about", today=TODAY, now=NOW)
    assert about.template == BECOMING
    assert not about.template.startswith("Becoming is by")

    follow = machine.step(session, "author", today=TODAY, now=NOW)
    assert follow.tools[0].payload["title"] == "Piranesi"
    assert follow.template == "Piranesi is by Susanna Clarke."

    missing = machine.step(
        session,
        "what's The Invisible Library about and who is the author",
        today=TODAY,
        now=NOW,
    )
    assert missing.template == "I don't have that on file."
    assert missing.tools[0].payload["author"] is None
    assert missing.tools[0].payload["summary"] is None
    assert "Michelle Obama" not in missing.template
    assert "Susanna Clarke" not in missing.template
    assert "Piranesi" not in missing.template
    assert "White House" not in missing.template
