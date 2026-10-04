"""The call without a microphone. No Claude and no Atlas."""

import json
from datetime import date, datetime, timezone

import numpy as np

from bookly_support.agent.provider import ChatReply, ChatRequest
from bookly_support.agent.return_agent import ReturnAgent
from bookly_support.voice.desk import CALL_GREETING, spoken_text
from bookly_support.voice.turns import FRAME_SAMPLES, TurnDetector

from test_allowlist import FakeStore, _order

PACKED = "It is being packed at the Bookly warehouse."


class _Sessions(FakeStore):
    def __init__(self, orders: list[dict]) -> None:
        super().__init__(orders)
        self.sessions: dict[str, dict] = {}

    def get_customer(self, customer_id: str) -> dict:
        assert customer_id == self.customer_id
        return {"id": customer_id, "name": "Becky Alvarez", "email": "becky@bookly.test"}

    def create_session(self, customer_id: str) -> dict:
        document = {
            "_id": f"conv_voice_{len(self.sessions) + 1}",
            "customerId": customer_id,
            "phase": "identify_order",
        }
        self.sessions[document["_id"]] = dict(document)
        return dict(document)

    def load_session(self, customer_id: str, conversation_id: str) -> dict | None:
        document = self.sessions.get(conversation_id)
        if document is None or document.get("customerId") != customer_id:
            return None
        return dict(document)

    def save_session(self, document: dict) -> None:
        self.sessions[document["_id"]] = dict(document)


class _Template:
    def phrase(self, turn, message, customer_name=None, memory=None):
        del turn, message, customer_name, memory
        return None


def _progress() -> dict:
    return {
        "orderId": "BLY-44120",
        "title": "Klara and the Sun",
        "placedAt": datetime(2026, 10, 1, 9, tzinfo=timezone.utc),
        "deliveredAt": None,
        "status": "packing",
        "statusDetail": PACKED,
        "refundableCents": 1700,
        "paymentMethodId": "pm_becky_visa",
        "genre": "fiction",
    }


def _agent(orders: list[dict]) -> ReturnAgent:
    return ReturnAgent(_Sessions(orders), _Template())


def _frame() -> np.ndarray:
    return np.zeros(FRAME_SAMPLES, dtype=np.float32)


def test_call_opens_with_the_fixed_greeting_and_no_order_facts() -> None:
    assert CALL_GREETING == (
        "Hi, thanks for calling Bookly. My name is Mara, and I'm your AI assistant. "
        "How can I help you?"
    )
    lowered = CALL_GREETING.casefold()
    assert "bly-" not in lowered
    assert "order" not in lowered
    assert "receipt" not in lowered
    assert "visa" not in lowered
    assert "day" not in lowered
    assert "$" not in CALL_GREETING
    assert "%" not in CALL_GREETING


def test_where_is_my_order_returns_the_stored_status() -> None:
    reply = _agent([_progress()]).reply(
        ChatRequest(message="where is my order", customer_id="cust_becky")
    )
    assert reply.step == "Step: order status"
    assert "BLY-44120" in reply.reply
    assert "Klara and the Sun" in reply.reply
    assert "packing" in reply.reply
    assert PACKED in reply.reply
    assert spoken_text(reply) == reply.reply
    assert "Step:" not in spoken_text(reply)
    assert "list_recent_orders" not in spoken_text(reply)


def test_spoken_text_is_the_checker_reply() -> None:
    reply = _agent([_progress()]).reply(
        ChatRequest(message="where is my order", customer_id="cust_becky")
    )
    assert spoken_text(reply) == reply.reply
    payload = {
        "spoken": spoken_text(reply),
        "step": reply.step,
        "tools": [tool.name for tool in reply.tools],
    }
    assert payload["step"] not in payload["spoken"]
    assert payload["tools"][0] not in payload["spoken"]


def test_a_short_list_is_spoken_when_the_buttons_hold_the_titles() -> None:
    reply = _agent(
        [
            _order("BLY-22018", "The Midnight Library", date(2026, 9, 24), date(2026, 9, 26), 1699),
            _order("BLY-22002", "Circe", date(2026, 9, 11), date(2026, 9, 15), 1700),
        ]
    ).reply(ChatRequest(message="I want to return a product", customer_id="cust_becky"))
    spoken = spoken_text(reply)
    assert reply.reply.startswith("Which book do you want to return?")
    assert "The Midnight Library" not in reply.reply
    assert spoken.startswith(reply.reply)
    assert "The Midnight Library, BLY-22018" in spoken
    assert "Circe, BLY-22002" in spoken
    assert "Step:" not in spoken
    assert "list_recent_orders" not in spoken


def test_half_second_of_silence_ends_the_turn() -> None:
    detector = TurnDetector()
    frame = _frame()
    started = False
    for _ in range(3):
        if any(event.kind == "start" for event in detector.push_frame(frame, 0.9)):
            started = True
    assert started
    for _ in range(15):
        assert all(event.kind != "end" for event in detector.push_frame(frame, 0.1))
    ending = detector.push_frame(frame, 0.1)
    assert any(event.kind == "end" and event.audio is not None and event.audio.size > 0 for event in ending)


def test_speech_over_mara_is_a_barge_in() -> None:
    detector = TurnDetector()
    detector.set_mara_speaking(True)
    frame = _frame()
    for _ in range(4):
        assert all(event.kind != "barge" for event in detector.push_frame(frame, 0.9))
    assert any(event.kind == "barge" for event in detector.push_frame(frame, 0.9))
    assert detector.mara_speaking is False


def test_voice_source_stays_on_this_desk() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "bookly_support"
    text = "\n".join(path.read_text() for path in root.rglob("*.py")).casefold()
    assert "pipecat" not in text
    assert "livekit" not in text
    assert "daily-python" not in text
    assert "speech_to_speech" not in text
    assert "distil-small.en" in text
    assert "en_us-lessac-medium" in text


def test_socket_greeting_and_fake_transcript(monkeypatch) -> None:
    spoken: list[str] = []

    def fake_speech(text: str, cancel) -> object:
        del cancel
        spoken.append(text)
        yield 22050, b"\x00\x00"

    monkeypatch.setattr("bookly_support.voice.tts.iter_speech", fake_speech)
    monkeypatch.setattr("bookly_support.voice.models.ensure_models", lambda: None)

    from bookly_support.main import app
    from fastapi.testclient import TestClient

    agent = _agent([_progress()])
    app.state.agent = agent
    try:
        with TestClient(app) as client, client.websocket_connect("/api/voice") as socket:
            socket.send_json({"type": "start", "customer_id": "cust_becky"})
            greeting = _until(socket, "greeting")
            assert greeting["text"] == CALL_GREETING
            assert "BLY-" not in greeting["text"]
            assert "order" not in greeting["text"].casefold()
            socket.send_json({"type": "text", "text": "where is my order"})
            reply = _until(socket, "reply")
            _until(socket, "audio_start")
    finally:
        if hasattr(app.state, "agent"):
            del app.state.agent

    assert isinstance(reply, dict)
    assert reply["step"] == "Step: order status"
    assert reply["spoken"] == reply["text"]
    assert "packing" in reply["text"]
    assert PACKED in reply["text"]
    assert "Step:" not in reply["spoken"]
    assert "list_recent_orders" not in reply["spoken"]
    assert CALL_GREETING in spoken
    assert reply["spoken"] in spoken
    parsed = ChatReply(
        reply=reply["text"],
        intent=reply["intent"],
        step=reply["step"],
        tools=[],
        conversation_id=reply["conversation_id"],
    )
    assert spoken_text(parsed) == reply["spoken"]


def _until(socket, kind: str) -> dict:
    for _ in range(40):
        message = socket.receive()
        text = message.get("text")
        if not text:
            continue
        data = json.loads(text)
        if data.get("type") == kind:
            return data
    raise AssertionError(kind)
