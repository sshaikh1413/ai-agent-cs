# Bookly return desk

Mara helps Becky Alvarez return a book. Becky is already signed in as `cust_becky`. There is no login screen.

The chat is the React desk (typed or spoken English, `en-US`). The API is a FastAPI state machine. It decides which Mongo tool may run. Claude phrases the tool JSON. A fact checker replaces the draft when an order id, receipt id, amount, date, or card tail was not in that JSON.

Tools, each scoped by `customerId`:

- `list_recent_orders`
- `get_order`
- `get_refund_options`
- `start_return`

"About a week ago" is a `placedAt` window of 5–9 days. One match is selected. Two matches are a question. `start_return` runs only after she chooses original payment or store credit, and a second call returns the same receipt.

## Requirements

- CPython **3.12.14** (`.python-version` and `requires-python`)
- [uv](https://docs.astral.sh/uv/) 0.12 or newer
- Node.js 22 and npm

## Secrets

The process needs `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID`, and `MONGODB_URI`. `ANTHROPIC_MODEL` is optional; the desk always calls `claude-sonnet-5-5` (`anthropic:claude-sonnet-5-5`).

Copy `.env.example` for the names. Put the values in the environment of the API process. Do not commit them.

Pydantic AI 2.48.0 sends `extra_headers` on each Anthropic messages request. This app sets `anthropic-workspace-id` there, and also as the Anthropic client's `default_headers`, so every request from that client includes the workspace.

## Run locally

API on port **8642** (binds `0.0.0.0`):

```bash
uv python install 3.12.14
uv sync
uv run uvicorn bookly_support.main:app --host 0.0.0.0 --port 8642
```

Chat UI on port **8643**:

```bash
cd frontend
npm install
npm run dev
```

Open [http://127.0.0.1:8643](http://127.0.0.1:8643). Vite proxies `/api` to the API.

## Tests

Pure tests (no Atlas, no Claude):

```bash
uv run pytest -m "not live"
```

The Becky script against Atlas and Claude:

```bash
uv run pytest -m live
```

That script skips when the environment variables above are missing.
