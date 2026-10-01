"""Becky's return, against Atlas and Claude. Skipped when secrets are absent."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live

_REQUIRED = ("ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "MONGODB_URI")


def test_becky_return_script() -> None:
    if any(not os.environ.get(name, "").strip() for name in _REQUIRED):
        pytest.skip("Atlas and Claude secrets are not in the environment")

    from fastapi.testclient import TestClient

    from bookly_support.main import app, get_agent

    with TestClient(app) as client:
        agent = get_agent()
        before = agent.store.count_completed_returns("cust_becky", "BLY-22018")

        first = client.post("/api/chat", json={"message": "I want to return a product"})
        assert first.status_code == 200, first.text
        body = first.json()
        assert "The Midnight Library" in body["reply"]
        assert "Circe" in body["reply"]
        assert [tool["name"] for tool in body["tools"]] == ["list_recent_orders"]
        conversation_id = body["conversation_id"]
        assert agent.store.count_completed_returns("cust_becky", "BLY-22018") == before

        second = client.post(
            "/api/chat",
            json={
                "message": "the one from about a week ago",
                "conversation_id": conversation_id,
            },
        )
        assert second.status_code == 200, second.text
        picked = second.json()
        names = [tool["name"] for tool in picked["tools"]]
        assert "start_return" not in names
        assert "get_refund_options" in names
        assert "Midnight Library" in picked["reply"]
        assert "4242" in picked["reply"]
        assert "credit" in picked["reply"].lower()
        assert agent.store.count_completed_returns("cust_becky", "BLY-22018") == before
        if before == 0:
            assert "rcpt_" not in picked["reply"]

        third = client.post(
            "/api/chat",
            json={
                "message": "the original payment method",
                "conversation_id": conversation_id,
            },
        )
        assert third.status_code == 200, third.text
        done = third.json()
        assert [tool["name"] for tool in done["tools"]] == ["start_return"]
        receipt = agent.store.completed_receipt("cust_becky", "BLY-22018")
        assert receipt is not None
        assert receipt["_id"] in done["reply"]
        assert "4242" in done["reply"]
        assert "16.99" in done["reply"]
        assert agent.store.count_completed_returns("cust_becky", "BLY-22018") == max(before, 1)

        fourth = client.post(
            "/api/chat",
            json={"message": "no", "conversation_id": conversation_id},
        )
        assert fourth.status_code == 200, fourth.text
        closed = fourth.json()
        assert closed["tools"] == []
        session = agent.store.load_session("cust_becky", conversation_id)
        assert session is not None
        assert session["phase"] == "closed"

        assert agent.phraser.calls == 4
        assert agent.phraser.errors == []
