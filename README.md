# Bookly return desk

Mara helps a signed-in reader return a book. The desk signs in as Becky Alvarez (`cust_becky`) or Bob Hale (`cust_bob`). Becky is the default. Switching readers starts a new conversation. The model cannot choose the customer.

The sidebar lists Mara's profile in our words: warm, brief, a bookstore clerk, short spoken sentences, and the fact rules. That same text is the standing system prompt. Claude only phrases the tool JSON. The signed-in customer's name is included in that JSON when the desk has one. Under each reply, the page shows one step from the state machine (`Step: which order`, and the later steps for the reason, the offer, the refund choice, and the receipt). That step is not part of the spoken reply. When a conversation starts and this customer has been here before, Mara's opening is a welcome, using their name when we know it: "Becky, it's good to see you again." It does not quote a stored reason or paste their earlier sentence. A return with no reason does not gain one. A customer with no completed return and no memory row gets no welcome.

The chat is the React desk (typed or spoken English, `en-US`). The API is a FastAPI state machine. It decides which Mongo tool may run. Claude phrases the tool JSON and does not invent a book title, an author, a plot, a percent, a discount code, or a shipment status. Replies are short and spoken, with contractions, and they do not read field names. A fact checker replaces the draft when an order id, receipt id, amount, date, card tail, percent, title, author, plot phrase, shipment status, or status detail was not in that JSON. On a late delivery it also replaces a draft that says gift or birthday when those words are not in the customer's reason. That reason is included in the phrasing JSON. If a memory of last time is included, the checker also replaces a draft that recites that reason, or says "you said", when this turn's message does not contain those words.

Tools:

- `list_recent_orders`, `get_order`, `get_refund_options`, and `start_return`, each scoped by `customerId`
- `recommend_book`, while offering empathy for a horror return that was not a late delivery, and again after the return is finished if they ask for a book
- `lookup_catalog`, when they ask who the author is or what the book is about. The payload is that title's author and one-sentence summary
- `issue_goodwill_discount`, only when the reason is a late delivery. One 20% code per customer and order

After the order is selected, Mara asks why. Claude labels the words they type (see *How Mara understands a message*), and the label is stored on the completed return as `sentiment` (`negative`, `neutral`, or `positive`) next to `reason` and `reasonKind`. That label can change the apology opening only. A late delivery (including a birthday or a gift) still gets that 20% code and no recommendation. The apology follows what their reason is about, not their exact words: Mara does not repeat or quote the sentence back. Claude labels a `reason_topic` (late, damaged, wrong book, duplicate, changed mind, not for me, other), with keywords in `reasons.reason_topic` as the fallback, and the line comes from that ("I'm sorry The Midnight Library wasn't your kind of book. Not every story clicks, and that's okay."). It mentions a gift or a birthday only when their reason includes those words, and the percent and code are copied from the discount. A horror book with any other reason still gets one non-horror catalog title the reader does not already own, and no discount. Any other reason gets empathy only. The title is chosen in our code: skip horror, skip titles they already own, then pick from the order id so the same order always gets the same book. Then she asks for the Visa or store credit. Closed phrases (original payment, Visa, store credit, and the other phrases already listed in code) still select that destination. Any other sentence uses Claude's `destination` label, and only while Mara is asking for a destination. Otherwise Mara asks again. Claude does not choose the destination, and it does not invent the amount, last4, or code. `start_return` stores the reason text, `reasonKind`, and that sentiment label, and runs only after that choice. A second call returns the same receipt and does not rewrite a return that is already stored.

Once the return is done, "return", "return another book", or "I want to return a book" asks which book again. The reply is one short question and one button per order that does not already have a completed return. That return stays stored. Clicking a button or typing a title still picks one of the books that remain. Part of a title, a description, or a misspelling finds the book too: "something gothic" is Mexican Gothic, "the one about a library" is The Midnight Library, "the witch book about Greek myths" is Circe, "Piranessi" is Piranesi. Claude picks the `order_id` from this customer's listed orders (and the machine keeps it only when it is on that list); a distinctive title word or a near spelling (`resolve.partial_title_matches`) is the fallback. Two matches are a question. There is no vector search: each customer has a handful of orders, and Claude already sees their titles. Delivered orders and orders still on the way keep the same marks. "where is my order" and "where is The Night Circus?" still answer from the stored status, including a returned order when they name it. "do you recommend any books for me?" calls that same pick. The reply is the one title from the tool result. The offer does not include the summary. If nothing is left, she says so and does not name a book. A goodbye still closes the chat. Any other message asks if they need something else.

After a return in this conversation is done, "shipping label", "shipping label?", "send the label", and "where's my label" open that return's parcel label. A card refund writes a receipt only. The first of those asks stores carrier Bookly Parcel and a made-up tracking number on the return, and a label document, the same way as the store-credit exception. The chat offers the same parcel-label download. A second ask returns that same tracking number. The PDF is built with fpdf2 from the stored carrier, the tracking number, and the customer's shipping address. No carrier is called. If this conversation has no completed return, Mara says there isn't a label yet because no return is done. She does not invent one, and she does not open the policy topic list for that phrase.

After a recommendation, "who is the author?", "author", "who wrote it", "what is it about?", or "what is the book about?" use that recommended title. If no recommendation is in play, those questions use the order title on the session. A question that names a title, such as "what's Becoming about and who is the author" or "who wrote Becoming", looks that catalog row up instead. Mara copies that row's author and the stored one-sentence summary. If the named title is not in the catalog, she says she does not have that, and she names no author and no plot. The step on that turn is "Step: about this book".

A reader can ask where an order is: "where is my order", "order status", "has it shipped", "is it out for delivery", or "what's the status of BLY-...". Mara copies the status and the status detail stored on that order, and she includes the order id and the title from the tool payload. One order that is still being sent is the answer. Two or more are listed, and she asks which, unless they named an id or a title. A delivered order is answered too when they name it. The step on that turn is "Step: order status". The question does not start a return, and it is not taken as a return reason or a refund choice. Closed refund phrases and Claude's destination label stay as they are.

A general shop question is answered from one Bookly policy article in the `policies` collection. `get_policy_article` returns that one article. Claude picks one article id from the listed articles. The machine uses it only when that id is on the list. Otherwise Mara asks which topic, and the same choice buttons used for books list the topics. She may say only that article. The checker rejects a day count, a dollar amount, or a code that was not in the payload, and it rejects a claim that a sign-in code was sent or that an email address has an account. The return window stays the existing policy length, 30 days, filled into the returns article when it is read. That article does not store a second copy of the number. Cancel and address-change articles state the rule and do not write. "What's my discount code?" reads her `discounts` row. Order status and returns stay on her own orders. Reset does not delete these articles. There is no Atlas Vector Search index.

Typing "FAQ" (or "FAQs", "frequently asked questions") lists the five questions people ask most as buttons: the return window, refund timing, shipping, cancelling, and a damaged or wrong book. A sixth button, "Show more questions", lists the next five, and so on until every policy article has been offered. Clicking a question answers it from that one policy article, the same way as a typed policy question, and the chat shows the question as the reader's message. The list and the answer do not change the step, so a return in progress picks up where it was. The questions are in `FAQ` in `agent/articles.py`; the answers are not stored twice. A clicked button sends `faq:<article id>` or `faq:more:<n>`, so a typed "returns" still starts a return.

"Is it too late to return a book?", with no title, lists every recent order. Each line copies a mark computed from `deliveredAt`, `returnWindowDays`, and `status`: delivered and inside the 30-day window, delivered and past the 30-day window, or still on the way with the stored trip status (packing, shipped, on the way, or out for delivery). Claude copies those marks and does not invent a status or a title. A draft that names a status or a title that was not in the tool JSON is replaced. The step is "Step: which book". Naming the book in the same sentence skips the list. Naming a book that is still on the way says it has not been delivered and repeats that stored status. It does not start a return, and it is not called past the window. A book still inside the window continues the normal return: why, then Visa or store credit, and "card is fine" still selects the Visa. A book past the window cannot go back on the card. Mara says when it was ordered and delivered, how many days past the 30-day return window it is now (counted from the delivery date), and that it cannot go back on the card. Then she asks "What is the reason for the return?", unless they already said, and offers a one-time store-credit exception for the refundable amount. "I will take it", "I'll take it", and "yes" after that window line stay on the book already named. With no reason stored, she asks for the reason for the return and does not list the other orders. After a reason, she offers store credit only. A later clear yes accepts that exception and writes it. Closed yes phrases stay as they are. Any other sentence on that offer uses Claude's `offer_reply` label: accept, refuse, or unsure. That accepts "yes", "yeah that'd be great", "yeah that would be great", "that works", "sounds good", "sure", "I'll take it", and "I will take it". A clear no ("no", "never mind", "no thanks") does not write and does not switch the offer to the card. An unrelated sentence stays on the offer and does not write. "Card is fine" or "can I get it on my Visa instead?" on that offer does not start a Visa refund. Mara says the book is past the 30 days, so it can't go back on the card, and asks again whether they want the store credit, in different words from the first offer. "Yes, but on my Visa" is that same card question, not a yes. Yes writes one return with destination store credit and an exception flag, even though the order is outside the window. A second yes returns the same receipt. The reason and reasonKind are stored. The desk then opens two PDFs built with fpdf2: the return receipt at `/api/receipts/{id}`, and a prepaid parcel label at `/api/labels/{id}`. The label uses the carrier name stored on the return, a tracking number stored on the return, Becky's name, and the shipping address on her customer record. It does not call a carrier. A draft that refunds the Visa on that book, or names FedEx, UPS, USPS, or DHL when that carrier was not stored, is replaced.

`scripts/seed_past_window.py` upserts Becky's older delivered order BLY-18440, Piranesi, and her shipping address. It does not change the in-window delivered orders or BLY-44120 through BLY-44123.

Orders still being sent use the customer-facing statuses packing, shipped, on the way, and out for delivery. Each one stores a title and a short status detail. They have no delivery date, so the existing return window does not treat them as eligible, and they are not marked delivered late. `scripts/seed_in_progress.py` upserts those orders for Becky and Bob. It does not change customers, returns, discounts, sessions, or the delivered orders BLY-22018, BLY-22002, BLY-22044, and BLY-33010.

When that write completes, the desk shows a download for a one-page PDF. The file is built with fpdf2 from the stored return, the order, and the customer. It is not written by the model, and it does not call a payment processor.

"About a week ago" is a `placedAt` window of 5–9 days. One match is selected. Two matches are a question.

Readers remember a title or roughly when they ordered, not an order number. "I want to return a product" with no book asks first: "Do you remember the book's title, or about when you ordered it?" The chat still shows the book buttons with that question; the call does not read them yet (`read_choices` is false). A title, an order id, or a date answers it. "I don't remember", "list them", or a second miss lists every order. On a call (`ChatRequest.channel` is `voice`), a book Mara cannot place, or a date with no order, is not followed by the whole list read aloud: she says she couldn't find it and asks "Would you like me to read your recent orders?" A yes reads them (title and order date); a no asks for the title or the date again. "No", "wrong one", or "not that one" right after she names a book means she has the wrong book: she drops it and asks which one, instead of taking "no" as the reason. A date ("last month", "in September", "September 24th", "two weeks ago") is labeled by Claude as `ordered_after` and `ordered_before`, with closed phrases in `window.ordered_window` as the fallback. One order placed in that window is selected; more than one lists only those; none says so and lists everything. A reason said in the same sentence ("return The Midnight Library because it was boring", "the one from August, the pages were torn") is stored as the reason, and Mara does not ask why again. Order numbers stay on the buttons and in the chat, and typing one still selects it.

"Speak to a representative", "operator", "agent", "a real person", "customer service", and the like get "Of course. One moment, please, and I'll connect you with one of our agents." at any step, and nothing in progress is lost. "Are you a human?" is a question about Mara, not a transfer. On a call, the call ends once she has said it. There is no live transfer in this demo.

`scripts/seed_empathy.py` inserts Becky's in-window horror order and Bob when those documents are missing, and upserts catalog titles. Each title gets an author, filled only when one is missing, and a one-sentence summary. An order title that is not already stocked is added too. Horror genres are left as stored. It reads `MONGODB_URI` from the environment and does not delete existing documents.

**Reset demo** on the desk calls `POST /api/demo/reset`. It clears chat sessions so the next message starts a new conversation. It removes returns, receipts, parcel labels, and goodwill discounts for the delivered orders BLY-22018, BLY-22002, BLY-22044, BLY-33010, and BLY-18440, so those orders can be returned again. It does not delete customers, catalog rows, Becky's shipping address, or the in-progress orders BLY-44120 through BLY-44123, and it does not change their statuses. Before a return is removed, a reason stored on it is copied to a `memory` row for that customer: customer id, order id, title, reason text, reasonKind, and sentiment. A return with no reason, including BLY-22018 when none was stored, does not get an invented one. Reset does not wipe memory rows already kept, and the welcome does not quote that reason.

## How Mara understands a message

Each turn makes one structured-output call (`agent/understand.py`). Claude returns an `Understanding`: the intents in the message, and only the slots this step needs (refund destination, a yes or no to an offer, a policy article id, the reason's kind and sentiment) with a confidence. Claude does not choose tools, write records, or pick the customer.

`validate` sits between that label and the state machine. It drops an article id that is not on this turn's list, keeps a destination only while Mara is asking for one, keeps a yes or no only during an offer, keeps sentiment and reason kind only when the message is the reason, and below 0.6 confidence drops anything that would write, so Mara asks again. The machine keeps its own precedence over the intents and matches order ids and titles against Atlas in code.

If the Claude call fails, `RuleUnderstander` labels the message from the closed phrases in `resolve.py`. Open wording gets no label in that case, and Mara asks again.

`agent/tool_agent.py` is a sketch of the next step and is not wired in: Claude chooses the tools from a short procedure, and every tool enforces policy in code.

## Voice call

**Voice** sits on the header row beside Reset demo. It opens a call panel, asks for the microphone, and Mara speaks first. The chat stays. If the microphone is blocked, the panel says so and typing still works. Switching Becky or Bob, or Reset demo, ends the call.

The opening is a script. It does not name an order, a price, or a return window:

"Hi, thanks for calling Bookly. My name is Mara, and I'm your AI assistant. How can I help you?"

After that, a return, a status, a policy question, store credit, the receipt, and the parcel label go through the same `ReturnAgent.reply` as the chat, including the checker. The panel shows the transcript, the same book buttons, and Open return receipt or Open parcel label. Saying a title, a date, or an order id selects it. Piper speaks only the reply the checker accepted, without order numbers or receipt ids (`unspoken_ids`); the panel still shows them. Amounts are written as dollars in the chat ("$16.99"; `templates.dollar_signs` adds the sign to any reply, from Claude or a template, that left it off) and said as words on the call ("sixteen dollars and ninety-nine cents"); a card's last four are said digit by digit. A caller cannot click a download, so on a call a "ready to download" line becomes "I've emailed you your return confirmation receipt and shipping label. Once we receive the book, we'll process your refund." (the receipt alone when there is no label yet). This demo does not send email. The step line, the tool name, and the JSON are not spoken. When the buttons carry a title the sentence left off, she says that short list as well, as the title and the day it was ordered ("Circe, ordered September 11"), never the order number.

The browser sends 16 kHz PCM over `/api/voice`, with echo cancellation. Silero VAD ends a turn after about half a second of silence and stops playback if the customer speaks. faster-whisper `distil-small.en` transcribes English on CPU. Piper `en_US-lessac-medium` speaks one sentence at a time. This slice does not use Pipecat, LiveKit, Daily, or a speech-to-speech model, and it has no phone number.

Weights download on the first call into `~/.cache/bookly-voice`. They are not committed.

## Requirements

- CPython **3.12.14** (`.python-version` and `requires-python`)
- [uv](https://docs.astral.sh/uv/) 0.12 or newer
- Node.js 22 and npm

## Secrets

The process needs `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID`, and `MONGODB_URI`. `ANTHROPIC_MODEL` is optional; the desk always calls `claude-sonnet-5-5` (`anthropic:claude-sonnet-5-5`).

Copy `.env.example` for the names. Put the values in the environment of the API process. Do not commit them.

Pydantic AI 2.48.0 sends `extra_headers` on each Anthropic messages request. This app sets `anthropic-workspace-id` there, and also as the Anthropic client's `default_headers`, so every request from that client includes the workspace.

## Run locally

From the repo root, one command installs the Python packages and the chat UI:

```bash
npm install
```

That runs `uv sync` into `.venv`, then `npm install` in `frontend`.

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

Pure tests label messages from `tests/golden_understanding.py` instead of calling Claude. The same sentences are the evaluation set: `uv run pytest -m live tests/test_understanding_eval.py` sends them to Claude and checks each label.

The Becky script against Atlas and Claude:

```bash
uv run pytest -m live
```

That script skips when the environment variables above are missing.
