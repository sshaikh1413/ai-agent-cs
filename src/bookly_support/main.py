"""HTTP desk for Becky's return chat."""

from __future__ import annotations

import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from bookly_support.agent.phrasing import ClaudePhraser
from bookly_support.agent.provider import AgentProvider, ChatReply, ChatRequest, DeskInfo
from bookly_support.agent.return_agent import ReturnAgent
from bookly_support.agent.store import MongoStore
from bookly_support.config import ALLOWED_CUSTOMER_IDS, CUSTOMER_ID, load_settings

app = FastAPI(title="Bookly support desk", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8643",
        "http://localhost:8643",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def build_provider() -> ReturnAgent:
    settings = load_settings()
    store = MongoStore(settings.mongodb_uri)
    return ReturnAgent(store, ClaudePhraser(settings))


def get_agent() -> ReturnAgent:
    agent = getattr(app.state, "agent", None)
    if agent is None:
        agent = build_provider()
        app.state.agent = agent
    return agent


def _agent(request: Request) -> AgentProvider:
    return get_agent()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _customer(value: str | None) -> str:
    if value is None or not value.strip():
        return CUSTOMER_ID
    cleaned = value.strip()
    if cleaned not in ALLOWED_CUSTOMER_IDS:
        raise HTTPException(status_code=400, detail="That account isn't on this desk.")
    return cleaned


@app.get("/api/desk", response_model=DeskInfo)
def desk(request: Request, customer_id: str | None = None) -> DeskInfo:
    try:
        return _agent(request).desk(_customer(customer_id))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="The order list didn't load.",
        ) from None


_RECEIPT_ID = re.compile(r"rcpt_[a-z0-9]+")


@app.get("/api/receipts/{receipt_id}")
def receipt_pdf(receipt_id: str, customer_id: str | None = None) -> Response:
    if _RECEIPT_ID.fullmatch(receipt_id) is None:
        raise HTTPException(status_code=404, detail="That receipt isn't on this account.")
    pdf = get_agent().store.return_receipt_pdf(_customer(customer_id), receipt_id)
    if pdf is None:
        raise HTTPException(status_code=404, detail="That receipt isn't on this account.")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{receipt_id}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/demo/reset")
def demo_reset(request: Request) -> dict[str, int | str]:
    """Restore the seeded return flow. Does not delete customers, catalog, or orders."""

    del request
    try:
        return get_agent().store.reset_demo()
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="The demo didn't reset.",
        ) from None


@app.post("/api/chat", response_model=ChatReply)
def chat(body: ChatRequest, request: Request) -> ChatReply:
    try:
        return _agent(request).reply(body)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="The support desk failed before it could answer.",
        ) from None
