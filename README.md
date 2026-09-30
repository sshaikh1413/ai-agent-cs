# Bookly support desk

Mara is Bookly's customer support chat for an online bookstore. She handles three things:

- order status
- returns and refunds
- shipping, the return policy, and password reset

This slice runs on sample bookstore records. There is no account login, no database, and no model, order, or speech-vendor API key. Speech uses the browser Web Speech API.

A return is not confirmed in one shot. Mara asks for the order number, then the reason, and only then calls `start_return`. Vague questions such as "where's my stuff?" get a clarifying question before any lookup. When she does look something up, the reply names the mocked tool she called: `lookup_order`, `start_return`, or `send_password_reset`.

## Requirements

- CPython **3.12.14** (pinned in `.python-version` and `requires-python`)
- [uv](https://docs.astral.sh/uv/) 0.12 or newer
- Node.js 22 and npm

## Run locally

API on port **8642** (binds `0.0.0.0`):

```bash
uv python install 3.12.14
uv sync
uv run uvicorn bookly_support.main:app --host 0.0.0.0 --port 8642 --reload
```

Chat UI on port **8643**, in a second terminal (binds `0.0.0.0`):

```bash
cd frontend
npm install
npm run dev
```

Open [http://127.0.0.1:8643](http://127.0.0.1:8643). The Vite dev server proxies `/api` to the API. Leave `VITE_AGENT_BASE_URL` unset unless the API is on another origin (`frontend/.env.example`).

## What the demo can answer

| Order | Reader | On the desk |
| --- | --- | --- |
| BLY-10482 | Maya Chen (`maya.chen@email.com`) | Shipped. *The Midnight Library* and *Klara and the Sun*. Tracking BPX-4419082. |
| BLY-10991 | Maya Chen | Delivered. *Project Hail Mary*. Return window still open. |
| BLY-11004 | Jordan Okonkwo (`jordan.okonkwo@email.com`) | Delivered. *Tomorrow, and Tomorrow, and Tomorrow*. Return window closed. |
| BLY-11120 | Jordan Okonkwo | Processing. *Circe*. Can be cancelled before it ships. |
| BLY-09877 | Sam Rivera (`sam.rivera@email.com`) | Cancelled. *The House in the Cerulean Sea*. Refund already issued. |
| BLY-11205 | Sam Rivera | Out for delivery. *Piranesi*. |

Try these:

- "Where is order BLY-10482?" — Mara calls `lookup_order` and shows the trace.
- "I want to return a book." — she asks for the order number, then the reason, then calls `start_return`.
- "Where's my stuff?" — she asks which order instead of guessing.
- "I forgot my Bookly password." — she asks for the account email, then calls `send_password_reset`.
- "How long does standard shipping take?" — warehouse, timing, and price. No tool call.

Standard shipping is 5–7 business days and $5.95, free at $35 before tax. Expedited is 2 business days and $8.95. Returns are 30 days from delivery.

## Replacing the mock

The chat UI talks only to `frontend/src/agent/provider.ts`. That module calls `POST /api/chat` and `GET /api/desk`.

The server-side contract is `src/bookly_support/agent/provider.py`. `build_provider()` in `src/bookly_support/main.py` is the only line that selects the demo agent. The mocked tools live in `src/bookly_support/agent/tools.py`. Swap those for a real model and live order, returns, and password APIs without rewriting the UI.

## Tests

```bash
uv run pytest
```
