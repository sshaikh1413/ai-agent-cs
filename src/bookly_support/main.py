"""HTTP desk for the Bookly support chat.

The route handlers depend on ``AgentProvider``. ``build_provider`` is
the only line that chooses the demo agent.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from bookly_support.agent.mock import MockAgent
from bookly_support.agent.provider import AgentProvider, ChatReply, ChatRequest, DeskInfo

app = FastAPI(title="Bookly support desk", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8643",
        "http://localhost:8643",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
def build_provider() -> AgentProvider:
    """Return the agent implementation the API should call.

    Swap ``MockAgent`` for a provider that uses a real model and the
    order and returns APIs. The chat UI does not change.
    """

    return MockAgent()


app.state.agent = build_provider()


def _agent(request: Request) -> AgentProvider:
    agent: AgentProvider = request.app.state.agent
    return agent


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/desk", response_model=DeskInfo)
def desk(request: Request) -> DeskInfo:
    return _agent(request).desk()


@app.post("/api/chat", response_model=ChatReply)
def chat(body: ChatRequest, request: Request) -> ChatReply:
    try:
        return _agent(request).reply(body)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="The support desk failed before it could answer.",
        ) from exc
