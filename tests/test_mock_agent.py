import ast
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from bookly_support.agent.mock import ASK_RESET_EMAIL, ASK_RETURN_ORDER, ASK_RETURN_REASON, MockAgent
from bookly_support.agent.provider import ChatReply, ChatRequest, ChatTurn
from bookly_support.agent.tools import lookup_order, send_password_reset, start_return
from bookly_support.main import app

TODAY = date(2026, 9, 30)


def _ask(message: str, history: list[ChatTurn] | None = None) -> ChatReply:
    return MockAgent(today=TODAY).reply(ChatRequest(message=message, history=history or []))


def _turns(*pairs: tuple[str, str]) -> list[ChatTurn]:
    history: list[ChatTurn] = []
    for role, content in pairs:
        history.append(ChatTurn(role=role, content=content))  # type: ignore[arg-type]
    return history


def test_shipped_order_calls_lookup_order() -> None:
    result = _ask("Where is order BLY-10482?")
    assert result.intent == "order_status"
    assert [tool.name for tool in result.tools] == ["lookup_order"]
    assert "lookup_order" in result.reply
    assert "BPX-4419082" in result.reply
    assert "The Midnight Library" in result.reply
    assert "Klara and the Sun" in result.reply
    assert "Maya Chen" in result.reply
    assert "not delivered yet" in result.reply


def test_return_collects_order_then_reason_before_confirming() -> None:
    first = _ask("I want to return a book.")
    assert first.intent == "return_refund"
    assert first.tools == []
    assert ASK_RETURN_ORDER in first.reply
    assert "RA-" not in first.reply
    assert "start_return" not in first.reply

    second = _ask(
        "BLY-10991",
        _turns(("user", "I want to return a book."), ("assistant", first.reply)),
    )
    assert [tool.name for tool in second.tools] == ["lookup_order"]
    assert ASK_RETURN_REASON in second.reply
    assert "RA-10991" not in second.reply
    assert "Project Hail Mary" in second.reply

    third = _ask(
        "I changed my mind.",
        _turns(
            ("user", "I want to return a book."),
            ("assistant", first.reply),
            ("user", "BLY-10991"),
            ("assistant", second.reply),
        ),
    )
    assert [tool.name for tool in third.tools] == ["lookup_order", "start_return"]
    assert "start_return" in third.reply
    assert "RA-10991" in third.reply
    assert "$4.50" in third.reply
    assert "4242" in third.reply


def test_return_with_order_and_reason_in_one_message_confirms() -> None:
    result = _ask("I need to return BLY-10991. It arrived damaged.")
    assert [tool.name for tool in result.tools] == ["lookup_order", "start_return"]
    assert "RA-10991" in result.reply
    assert "label is free" in result.reply
    assert "$4.50" not in result.reply


def test_closed_window_is_confirmed_only_after_the_reason() -> None:
    first = _ask("Please refund order BLY-11004.")
    assert [tool.name for tool in first.tools] == ["lookup_order"]
    assert ASK_RETURN_REASON in first.reply
    assert "can't open a return" not in first.reply

    second = _ask(
        "I changed my mind.",
        _turns(("user", "Please refund order BLY-11004."), ("assistant", first.reply)),
    )
    assert "start_return" in [tool.name for tool in second.tools]
    assert "RA-11004" not in second.reply
    assert "closed" in second.reply
    assert "can't open a return" in second.reply


def test_damage_after_the_window_does_not_invent_an_authorization() -> None:
    result = _ask("BLY-11004 arrived damaged.")
    assert "start_return" in [tool.name for tool in result.tools]
    assert "RA-11004" not in result.reply
    assert "help@booklybooks.example" in result.reply


def test_processing_order_can_be_cancelled() -> None:
    result = _ask("Cancel order BLY-11120.")
    assert result.intent == "return_refund"
    assert "start_return" in [tool.name for tool in result.tools]
    assert "CX-11120" in result.reply
    assert "Circe" in result.reply
    assert "$22.15" in result.reply


def test_return_window_days_left_on_status() -> None:
    result = _ask("status of BLY-10991")
    assert result.intent == "order_status"
    assert "18 days left" in result.reply
    assert result.tools[0].name == "lookup_order"


def test_vague_order_question_asks_before_answering() -> None:
    for message in ("where's my stuff?", "I need help with an order"):
        result = _ask(message)
        assert result.intent == "clarify", message
        assert result.tools == []
        assert "order number" in result.reply.lower()
        assert "BPX-" not in result.reply
        assert "Maya" not in result.reply
        assert "RA-" not in result.reply


def test_password_reset_asks_then_calls_send_password_reset() -> None:
    first = _ask("I forgot my Bookly password.")
    assert first.intent == "password_reset"
    assert first.tools == []
    assert "I can't see or change your password." in first.reply
    assert ASK_RESET_EMAIL in first.reply
    assert "30 minutes" in first.reply
    assert "send_password_reset" not in [tool.name for tool in first.tools]

    second = _ask(
        "maya.chen@email.com",
        _turns(("user", "I forgot my Bookly password."), ("assistant", first.reply)),
    )
    assert [tool.name for tool in second.tools] == ["send_password_reset"]
    assert "send_password_reset" in second.reply
    assert "maya.chen@email.com" in second.reply
    assert "hello@booklybooks.example" in second.reply
    assert "30 minutes" in second.reply


def test_shipping_policy() -> None:
    result = _ask("How long does standard shipping take?")
    assert result.intent == "shipping"
    assert result.tools == []
    assert "Columbus, Ohio" in result.reply
    assert "$5.95" in result.reply
    assert "$8.95" in result.reply
    assert "$35.00" in result.reply


def test_return_policy_without_an_order() -> None:
    result = _ask("What's your return policy?")
    assert result.intent == "policy"
    assert result.tools == []
    assert "30 days" in result.reply
    assert "$4.50" in result.reply


def test_unknown_order_still_calls_lookup() -> None:
    result = _ask("Where is BLY-99999?")
    assert result.intent == "order_status"
    assert result.tools[0].name == "lookup_order"
    assert "BLY-99999" in result.reply
    assert "BLY-10482" in result.reply


def test_email_lists_that_readers_orders() -> None:
    result = _ask("What orders are on maya.chen@email.com?")
    assert result.intent == "order_status"
    assert result.tools[0].name == "lookup_order"
    assert "BLY-10482" in result.reply
    assert "BLY-10991" in result.reply
    assert "BLY-11120" not in result.reply


def test_title_on_the_wrong_email_is_not_mixed_up() -> None:
    result = _ask("Return Project Hail Mary for jordan.okonkwo@email.com")
    assert "lookup_order" in [tool.name for tool in result.tools]
    assert "maya.chen@email.com" in result.reply
    assert "not on jordan.okonkwo@email.com" in result.reply
    assert "RA-10991" not in result.reply


def test_follow_up_uses_the_order_from_history() -> None:
    result = _ask(
        "Can I return it?",
        _turns(
            ("user", "Where is order BLY-10482?"),
            ("assistant", "It shipped."),
        ),
    )
    assert result.intent == "return_refund"
    assert "BLY-10482" in result.reply
    assert "can't open a return yet" in result.reply
    assert "start_return" in [tool.name for tool in result.tools]


def test_out_for_delivery() -> None:
    result = _ask("Track BLY-11205")
    assert "out for delivery" in result.reply
    assert "Piranesi" in result.reply
    assert "BPX-4481106" in result.reply


def test_cancelled_refund_status() -> None:
    result = _ask("Was I refunded for the Cerulean Sea order?")
    assert "BLY-09877" in result.reply
    assert "cancelled" in result.reply.lower()
    assert "$21.94" in result.reply
    assert "9033" in result.reply
    assert result.tools[0].name == "lookup_order"


def test_recommendation_is_out_of_scope() -> None:
    result = _ask("Can you recommend a science fiction book?")
    assert result.intent == "out_of_scope"
    assert result.tools == []
    assert "help@booklybooks.example" in result.reply


def test_greeting() -> None:
    result = _ask("Hello")
    assert result.intent == "clarify"
    assert "Mara" in result.reply
    assert result.tools == []


def test_desk_lists_sample_orders() -> None:
    desk = MockAgent(today=TODAY).desk()
    assert desk.agent_name == "Mara"
    assert [order.id for order in desk.sample_orders] == [
        "BLY-10482",
        "BLY-10991",
        "BLY-11004",
        "BLY-11120",
        "BLY-09877",
        "BLY-11205",
    ]
    assert "Where's my stuff?" in desk.prompts


def test_tools_read_the_sample_book() -> None:
    found = lookup_order(TODAY, order_id="BLY-10482")
    assert found.name == "lookup_order"
    assert "BPX-4419082" in found.detail

    filed = start_return("BLY-10991", "I changed my mind", today=TODAY)
    assert filed.name == "start_return"
    assert "RA-10991" in filed.detail

    reset = send_password_reset("maya.chen@email.com", today=TODAY)
    assert reset.name == "send_password_reset"
    assert "maya.chen@email.com" in reset.summary


def test_provider_module_does_not_import_the_mock() -> None:
    source = Path("src/bookly_support/agent/provider.py").read_text()
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert all("mock" not in name and not name.endswith(".tools") for name in imported)


def test_chat_endpoint_includes_the_tool_trace() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/chat",
        json={"message": "Where is order BLY-10482?", "history": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "order_status"
    assert body["tools"][0]["name"] == "lookup_order"
    assert "BPX-4419082" in body["reply"]


def test_empty_message_is_rejected() -> None:
    client = TestClient(app)
    response = client.post("/api/chat", json={"message": "   ", "history": []})
    assert response.status_code == 422


def test_desk_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/api/desk")
    assert response.status_code == 200
    body = response.json()
    assert body["agent_name"] == "Mara"
    assert len(body["sample_orders"]) == 6
