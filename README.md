# Bookly return desk

Mara helps a signed-in reader return a book. The desk signs in as Becky Alvarez (`cust_becky`) or Bob Hale (`cust_bob`). Becky is the default. Switching readers starts a new conversation. The model cannot choose the customer.

The sidebar lists Mara's profile in our words: warm, brief, a bookstore clerk, short spoken sentences, and the fact rules. That same text is the standing system prompt. Claude only phrases the tool JSON. The signed-in customer's name is included in that JSON when the desk has one. Under each reply, the page shows one step from the state machine (`Step: which order`, and the later steps for the reason, the offer, the refund choice, and the receipt). That step is not part of the spoken reply. When a conversation starts and this customer has been here before, Mara's opening is a welcome, using their name when we know it: "Becky, it's good to see you again." It does not quote a stored reason or paste their earlier sentence. A return with no reason does not gain one. A customer with no completed return and no memory row gets no welcome.

The chat is the React desk (typed or spoken English, `en-US`). The API is a FastAPI state machine. It decides which Mongo tool may run. Claude phrases the tool JSON and does not invent a book title, an author, a plot, a percent, a discount code, or a shipment status. Replies are short and spoken, with contractions, and they do not read field names. A fact checker replaces the draft when an order id, receipt id, amount, date, card tail, percent, title, author, plot phrase, shipment status, or status detail was not in that JSON. On a late delivery it also replaces a draft that says gift or birthday when those words are not in the customer's reason. That reason is included in the phrasing JSON. If a memory of last time is included, the checker also replaces a draft that recites that reason, or says "you said", when this turn's message does not contain those words.

Tools:

- `list_recent_orders`, `get_order`, `get_refund_options`, and `start_return`, each scoped by `customerId`
- `recommend_book`, while offering empathy for a horror return that was not a late delivery, and again after the return is finished if they ask for a book
- `lookup_catalog`, when they ask who the author is or what the book is about. The payload is that title's author and one-sentence summary
- `issue_goodwill_discount`, only when the reason is a late delivery. One 20% code per customer and order

After the order is selected, Mara asks why. The words they type are scored with VADER and stored on the completed return as `sentiment` (`negative`, `neutral`, or `positive`) next to `reason` and `reasonKind`. That label can change the apology opening only. A late delivery (including a birthday or a gift) still gets that 20% code and no recommendation. The apology follows the words they typed. It mentions a gift or a birthday only when their reason includes those words, and the percent and code are copied from the discount. A horror book with any other reason still gets one non-horror catalog title the reader does not already own, and no discount. Any other reason gets empathy only. The title is chosen in our code: skip horror, skip titles they already own, then pick from the order id so the same order always gets the same book. Then she asks for the Visa or store credit. Closed phrases (original payment, Visa, store credit, and the other phrases already listed in code) still select that destination. Any other sentence is embedded with fastembed `0.8.1` and `BAAI/bge-small-en-v1.5` against a short list of example sentences we own for each destination. The closer one is used only when its best example is at least 0.80 cosine and at least 0.12 ahead of the other destination. Otherwise Mara asks again. Claude does not choose the destination, and it does not invent the amount, last4, or code. `start_return` stores the reason text, `reasonKind`, and that sentiment label, and runs only after that choice. A second call returns the same receipt and does not rewrite a return that is already stored.

Once the return is done, "do you recommend any books for me?" calls that same pick. The reply is the one title from the tool result. The offer does not include the summary. If nothing is left, she says so and does not name a book. A goodbye still closes the chat. Any other message asks if they need something else.

After a recommendation, "who is the author?", "author", "who wrote it", "what is it about?", or "what is the book about?" use that recommended title. If no recommendation is in play, those questions use the order title on the session. A question that names a title, such as "what's Becoming about and who is the author" or "who wrote Becoming", looks that catalog row up instead. Mara copies that row's author and the stored one-sentence summary. If the named title is not in the catalog, she says she does not have that, and she names no author and no plot. The step on that turn is "Step: about this book".

A reader can ask where an order is: "where is my order", "order status", "has it shipped", "is it out for delivery", or "what's the status of BLY-...". Mara copies the status and the status detail stored on that order, and she includes the order id and the title from the tool payload. One order that is still being sent is the answer. Two or more are listed, and she asks which, unless they named an id or a title. A delivered order is answered too when they name it. The step on that turn is "Step: order status". The question does not start a return, and it is not taken as a return reason or a refund choice. Closed refund phrases and the bge-small matcher stay as they are.

Orders still being sent use the customer-facing statuses packing, shipped, on the way, and out for delivery. Each one stores a title and a short status detail. They have no delivery date, so the existing return window does not treat them as eligible, and they are not marked delivered late. `scripts/seed_in_progress.py` upserts those orders for Becky and Bob. It does not change customers, returns, discounts, sessions, or the delivered orders BLY-22018, BLY-22002, BLY-22044, and BLY-33010.

When that write completes, the desk shows a download for a one-page PDF. The file is built with fpdf2 from the stored return, the order, and the customer. It is not written by the model, and it does not call a payment processor.

"About a week ago" is a `placedAt` window of 5–9 days. One match is selected. Two matches are a question.

`scripts/seed_empathy.py` inserts Becky's in-window horror order and Bob when those documents are missing, and upserts catalog titles. Each title gets an author, filled only when one is missing, and a one-sentence summary. An order title that is not already stocked is added too. Horror genres are left as stored. It reads `MONGODB_URI` from the environment and does not delete existing documents.

**Reset demo** on the desk calls `POST /api/demo/reset`. It clears chat sessions so the next message starts a new conversation. It removes returns, receipts, and goodwill discounts for the delivered orders BLY-22018, BLY-22002, BLY-22044, and BLY-33010, so those orders can be returned again. It does not delete customers, catalog rows, or the in-progress orders BLY-44120 through BLY-44123, and it does not change their statuses. Before a return is removed, a reason stored on it is copied to a `memory` row for that customer: customer id, order id, title, reason text, reasonKind, and sentiment. A return with no reason, including BLY-22018 when none was stored, does not get an invented one. Reset does not wipe memory rows already kept.

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

The destination tests embed with `BAAI/bge-small-en-v1.5`. The first run downloads that model through fastembed into the local fastembed cache.

The Becky script against Atlas and Claude:

```bash
uv run pytest -m live
```

That script skips when the environment variables above are missing.
