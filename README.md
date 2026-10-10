# Bookly Support Desk

An AI customer-support desk for an online bookstore, by chat or by voice. **Mara**, the assistant, handles book returns from start to finish, answers order-status and policy questions, and hands off to a person when asked.

The design rule: **Claude understands and phrases; code decides.** Claude reads each message and writes each reply. A state machine chooses which tool runs, applies every store policy, and a fact checker makes sure each reply only states facts the tools returned.

---

## What Mara can do

- **Returns, end to end.** Finds the book from a title, part of a title ("something gothic"), a description ("the witch book about Greek myths"), a misspelling, or roughly when it was ordered ("last month"). Asks why, responds with empathy, and offers a refund to the card on file or store credit. Then writes the return, with a downloadable receipt and a shipping label.
- **Past the 30-day window.** Says when the book was ordered and delivered and how many days past the window it is, then offers a one-time store-credit exception. The card is never offered for these.
- **Order status.** Reads the stored status of an order ("where is my order", "where's the circus book").
- **Store questions and FAQ.** Answers from Bookly's own policy articles. Typing **FAQ** lists the most-asked questions as buttons, with a *Show more questions* button for the rest.
- **Books.** Gives the author and a one-line summary from the catalog, and recommends a book the reader doesn't already own (never horror after a horror return).
- **Goodwill.** A late delivery gets a one-time 20% discount code.
- **Memory.** Welcomes a returning reader by name, without repeating what they said last time.
- **Handoff.** "Speak to a representative", "operator", "agent" and similar requests get a transfer message at any step.
- **Voice calls.** A browser call with speech recognition and text-to-speech, using the same agent and the same checks as the chat.

---

## How it works

```mermaid
flowchart LR
    A[Customer message<br/>chat or voice] --> B[Understand<br/>Claude, structured output]
    B --> C[Validate<br/>keep only what this step allows]
    C --> D[State machine<br/>picks the tool, applies policy]
    D --> E[(MongoDB Atlas)]
    D --> F[Template reply]
    F --> G[Phrase<br/>Claude rewrites in Mara's voice]
    G --> H{Fact checker}
    H -- grounded --> I[Reply]
    H -- unsupported fact --> F
```

Each turn goes through four layers:

1. **Understand** ([`agent/understand.py`](src/bookly_support/agent/understand.py)). One Claude call labels the message with a fixed schema: intents such as `return_item`, `order_status` or `human_agent`, plus details such as the order they mean, when they ordered, their reason and its tone, a refund choice, or a yes or no to an offer. Rule-based matching is the fallback if the call fails.
2. **Validate and decide** ([`agent/machine.py`](src/bookly_support/agent/machine.py)). The label is checked against the current step and dropped when confidence is low. The state machine then chooses one tool. A tool [allowlist](src/bookly_support/agent/allowlist.py) limits which tools each step may run. Claude never chooses tools, writes records, or picks the customer.
3. **Phrase** ([`agent/phrasing.py`](src/bookly_support/agent/phrasing.py)). Claude rewrites a template reply in Mara's voice: warm, brief, like a bookstore clerk. It sees only the tool results for this turn.
4. **Check** ([`agent/checker.py`](src/bookly_support/agent/checker.py)). The draft is rejected, and the template used instead, if it states an order id, amount, date, title, author, status, discount code or carrier that the tools didn't return.

### Tools

| Tool | Used for |
|---|---|
| `list_recent_orders`, `get_order` | Finding the book and its delivery window |
| `get_refund_options` | The refund amount and the card on file |
| `start_return` | Writing the return (once per order; a repeat call returns the same receipt) |
| `issue_parcel_label` | A shipping label with a stored carrier and tracking number |
| `issue_goodwill_discount` | A 20% code, only after a late delivery |
| `recommend_book`, `lookup_catalog` | Recommendations, author and summary |
| `get_policy_article`, `list_customer_discounts` | Store policy answers and the reader's own codes |

Every tool is scoped to the signed-in customer.

---

## Voice

The **Voice** button opens a call in the browser. It runs on your machine, with no phone number or third-party voice service:

| Stage | Technology |
|---|---|
| Microphone | 16 kHz PCM over the `/api/voice` WebSocket, with echo cancellation |
| End of turn | Silero VAD (about half a second of silence; speaking over Mara interrupts her) |
| Speech to text | faster-whisper `distil-small.en`, on CPU |
| Agent | The same agent and fact checker as the chat |
| Text to speech | Piper `en_US-lessac-medium`, one sentence at a time |

A call behaves differently from the chat where reading aloud would hurt:

- **Finding the book:** Mara asks for the title or the order date first. If she can't find it, she offers to read the recent orders instead of reading them all unprompted.
- **What's spoken:**
  - Order and receipt numbers are left out.
  - Amounts are said as dollars ("sixteen dollars and ninety-nine cents").
  - Card digits are read one at a time.
- **Documents:** downloads become "I've emailed you your return confirmation receipt and shipping label." The demo doesn't actually send email.
- **Handoff:** a request for a person ends the call after Mara's transfer message.

Voice models (about 400 MB) download to `~/.cache/bookly-voice` on the first call.

---

## Tech stack

| Layer | Technology |
|---|---|
| API | Python 3.12, FastAPI, Pydantic AI |
| Model | Claude (`claude-sonnet-5-5`) for understanding and phrasing |
| Data | MongoDB Atlas (`bookly` database) |
| Chat UI | React 19, Vite, Tailwind CSS, shadcn/ui |
| Voice | Silero VAD, faster-whisper, Piper |
| Documents | fpdf2, for receipts and shipping labels |

---

## Getting started

### Prerequisites

- **Python 3.12.14**, managed by [uv](https://docs.astral.sh/uv/) 0.12 or newer
- **Node.js 22+** and npm
- A **MongoDB Atlas** cluster
- An **Anthropic API key**, plus a workspace ID if the key isn't tied to one workspace

### 1. Clone and install

```bash
git clone git@github.com:sshaikh1413/ai-agent-cs.git
cd ai-agent-cs
uv python install 3.12.14
npm install          # runs `uv sync` for the API, then installs the chat UI
```

### 2. Configure

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

| Variable | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Your Claude API key |
| `ANTHROPIC_WORKSPACE_ID` | Yes | Starts with `wrkspc_`, from the Anthropic Console under Settings → Workspaces |
| `MONGODB_URI` | Yes | `mongodb+srv://user:password@cluster.../?appName=...` |
| `ANTHROPIC_MODEL` | No | Ignored; the desk always uses `claude-sonnet-5-5` |

`.env` is git-ignored. Never commit it.

### 3. Load the demo data

The seed scripts fill the `bookly` database with two demo readers, their orders, the catalog and the store policies. Run them in this order on a new database. None of them delete anything, and each is safe to run again.

```bash
uv run --env-file .env python scripts/seed_base.py              # Becky, her card, two recent orders, the 30-day window
uv run --env-file .env python scripts/seed_empathy.py           # catalog, Bob, horror order
uv run --env-file .env python scripts/seed_in_progress.py       # orders still being shipped
uv run --env-file .env python scripts/seed_past_window.py       # an order past the window, shipping address
uv run --env-file .env python scripts/seed_policy_articles.py   # store policy articles
```

### 4. Run

In two terminals:

```bash
# API on port 8642
uv run --env-file .env uvicorn bookly_support.main:app --host 0.0.0.0 --port 8642
```

```bash
# Chat UI on port 8643
cd frontend && npm run dev
```

Open **http://127.0.0.1:8643**. Vite forwards `/api` requests to the API. Voice needs `localhost` or `127.0.0.1`, since browsers only allow the microphone on secure origins.

---

## Trying it out

The desk is signed in as one of two demo readers. Switch with the buttons in the header; switching starts a new conversation.

| Reader | Good for |
|---|---|
| **Becky Alvarez** (default) | Every flow: in-window returns, a horror book, a book past the window, orders still in transit |
| **Bob Hale** | A slow delivery (*A Gentleman in Moscow*) for the late-delivery apology and 20% code, plus two orders in transit |

Things to try:

- `I want to return a book` → `the gothic one` → `it was too scary` → `store credit`
- `I want to return Piranesi because the pages were torn` → `can I get it on my Visa instead?`
- `Where is my order?` or `where's the circus book`
- `FAQ`
- `What's The Midnight Library about?`
- `Can I speak to a representative?`

**Reset demo** clears conversations and removes completed returns, receipts, labels and discount codes, so every book can be returned again. Customers, orders, the catalog and remembered reasons are kept.

---

## Tests

```bash
uv run pytest -m "not live"                                         # fast; no network
uv run --env-file .env pytest -m live                               # against Atlas and Claude
uv run --env-file .env pytest -m live tests/test_understanding_eval.py   # Claude's labels vs. the golden set
```

The offline tests label messages from a golden set ([`tests/golden_understanding.py`](tests/golden_understanding.py)) instead of calling Claude. The same sentences make up the live evaluation that checks Claude's labels. Live tests are skipped when the environment variables are missing.

---

## Project structure

```text
src/bookly_support/
├── main.py              FastAPI app and routes
├── config.py            Settings from the environment
├── agent/
│   ├── return_agent.py  One turn: session → state machine → phrasing → checker
│   ├── understand.py    Claude's structured label for each message, with a rule fallback
│   ├── machine.py       The state machine: steps, tool choice, policy
│   ├── allowlist.py     Which tools each step may run
│   ├── phrasing.py      Mara's voice and the phrasing call
│   ├── checker.py       Rejects drafts with unsupported facts
│   ├── templates.py     The fallback wording for every reply
│   ├── resolve.py       Phrase matching: titles, refund choices, handoff
│   ├── window.py        Return window and "when I ordered it" dates
│   ├── articles.py      Policy articles and the FAQ list
│   ├── store.py         MongoDB access
│   └── receipt_pdf.py, label_pdf.py   Receipt and shipping-label documents
└── voice/
    ├── socket.py        The /api/voice WebSocket call loop
    ├── desk.py          What the call says (ids removed, amounts in words)
    ├── vad.py, turns.py Turn detection
    └── stt.py, tts.py   faster-whisper and Piper
frontend/src/
├── components/          Support desk, message box, call panel
├── speech/              Microphone, playback, browser speech input
└── agent/               API client and the "working…" lines
scripts/                 Seed scripts for the demo data (start with seed_base.py)
tests/                   Offline and live tests, golden labels
```

### API

| Route | Purpose |
|---|---|
| `POST /api/chat` | One chat turn |
| `GET /api/desk` | The signed-in reader, recent orders and prompts |
| `WS /api/voice` | A voice call |
| `GET /api/receipts/{id}`, `GET /api/labels/{id}` | Receipt and shipping-label downloads |
| `POST /api/demo/reset` | Reset the demo |
| `GET /api/health` | Health check |
