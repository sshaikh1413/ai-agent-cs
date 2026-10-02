# Bookly return desk

Mara helps a signed-in reader return a book. The desk signs in as Becky Alvarez (`cust_becky`) or Bob Hale (`cust_bob`). Becky is the default. Switching readers starts a new conversation. The model cannot choose the customer.

The sidebar lists Mara's profile in our words: warm, brief, a bookstore clerk, and the fact rules. That same text is the standing system prompt. Claude only phrases the tool JSON. The signed-in customer's name is included in that JSON when the desk has one. Under each reply, the page shows one step from the state machine (`Step: which order`, and the later steps for the reason, the offer, the refund choice, and the receipt). When a conversation starts, Mara's opening quotes that customer's latest completed return: the stored title, and the stored reason text only when the return has one. A return with no reason does not gain one. A customer with no completed return gets no memory line.

The chat is the React desk (typed or spoken English, `en-US`). The API is a FastAPI state machine. It decides which Mongo tool may run. Claude phrases the tool JSON and does not invent a book title, an author, a plot, a percent, or a discount code. A fact checker replaces the draft when an order id, receipt id, amount, date, card tail, percent, title, author, or plot phrase was not in that JSON. On a late delivery it also replaces a draft that says gift or birthday when those words are not in the customer's reason. That reason is included in the phrasing JSON.

Tools:

- `list_recent_orders`, `get_order`, `get_refund_options`, and `start_return`, each scoped by `customerId`
- `recommend_book`, while offering empathy for a horror return that was not a late delivery, and again after the return is finished if they ask for a book
- `lookup_catalog`, when they ask who the author is or what the book is about. The payload is that title's author and one-sentence summary
- `issue_goodwill_discount`, only when the reason is a late delivery. One 20% code per customer and order

After the order is selected, Mara asks why. The words they type are scored with VADER and stored on the completed return as `sentiment` (`negative`, `neutral`, or `positive`) next to `reason` and `reasonKind`. That label can change the apology opening only. A late delivery (including a birthday or a gift) still gets that 20% code and no recommendation. The apology follows the words they typed. It mentions a gift or a birthday only when their reason includes those words, and the percent and code are copied from the discount. A horror book with any other reason still gets one non-horror catalog title the reader does not already own, and no discount. Any other reason gets empathy only. The title is chosen in our code: skip horror, skip titles they already own, then pick from the order id so the same order always gets the same book. Then she asks for the Visa or store credit. `start_return` stores the reason text, `reasonKind`, and that sentiment label, and runs only after that choice. A second call returns the same receipt and does not rewrite a return that is already stored.

Once the return is done, "do you recommend any books for me?" calls that same pick. The reply is the one title from the tool result. The offer does not include the summary. If nothing is left, she says so and does not name a book. A goodbye still closes the chat. Any other message asks if they need something else.

After a recommendation, "who is the author?", "author", "who wrote it", "what is it about?", or "what is the book about?" use that recommended title. If no recommendation is in play, those questions use the order title on the session. A question that names a title, such as "what's Becoming about and who is the author" or "who wrote Becoming", looks that catalog row up instead. Mara copies that row's author and the stored one-sentence summary. If the named title is not in the catalog, she says she does not have that, and she names no author and no plot. The step on that turn is "Step: about this book".

When that write completes, the desk shows a download for a one-page PDF. The file is built with fpdf2 from the stored return, the order, and the customer. It is not written by the model, and it does not call a payment processor.

"About a week ago" is a `placedAt` window of 5–9 days. One match is selected. Two matches are a question.

`scripts/seed_empathy.py` inserts Becky's in-window horror order and Bob when those documents are missing, and upserts catalog titles. Each title gets an author, filled only when one is missing, and a one-sentence summary. An order title that is not already stocked is added too. Horror genres are left as stored. It reads `MONGODB_URI` from the environment and does not delete existing documents.

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
