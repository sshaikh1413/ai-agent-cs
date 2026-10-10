// The line under the pulse while Mara works. It is picked from what the reader
// sent, so a click on a book, a FAQ question, or a refund choice each get their
// own. These lines are only flavor: they never state a fact, a date, or an amount.

type Pick = (title?: string) => string[]

// One line per policy article, keyed by article id. FAQ buttons send "faq:<id>";
// the topic picker sends the bare id.
const ARTICLE_LINES: Record<string, string[]> = {
  returns: ["Reading the fine print on returns…", "Counting days on the returns calendar…"],
  "refund-timing": ["Following the money back home…", "Asking the till how fast it moves…"],
  "shipping-speed": ["Timing the delivery van with a stopwatch…", "Consulting the van's diary…"],
  cancel: ["Checking whether it's still on the packing table…"],
  "address-change": ["Checking whether the label's ink is still wet…"],
  "damaged-or-wrong": ["Putting on the reading glasses for a closer look…"],
  tracking: ["Following the parcel's footprints…"],
  "discount-code": ["Rattling the coupon drawer…"],
  "gift-order": ["Being very discreet about the gift wrap…"],
  "sign-in": ["Jiggling the front-door key…"],
  "where-we-ship": ["Unfolding the big shipping map…"],
  "what-we-sell": ["Squeezing a book to confirm it's real paper…"],
  "confirmation-email": ["Rummaging through the outbox…"],
  "sales-tax": ["Bracing for the tax table…"],
}

const GENERAL: string[] = [
  "Checking the order book…",
  "Leafing through the ledger…",
  "Thinking it over with a cup of tea…",
  "Consulting the shop cat…",
]

const RULES: Array<[RegExp, Pick]> = [
  [
    /^faq:more:|\bfaqs?\b|frequently asked|common questions/,
    () => ["Dusting off the FAQ binder…", "Flipping to the well-thumbed pages…", "Rounding up the usual questions…"],
  ],
  [
    /^bly-\d+$/,
    (title) =>
      title
        ? [`Pulling ${title} off the shelf…`, `Finding ${title} in the stacks…`, `Blowing the dust off ${title}…`]
        : ["Pulling that order off the shelf…", "Finding it in the stacks…"],
  ],
  [/\blabel\b/, () => ["Fetching the tape gun and a fresh label…", "Warming up the label printer…"]],
  [/too late|past the window|still return/, () => ["Squinting at the calendar…", "Counting days on my fingers…"]],
  [
    /where('s| is) my|order status|\bstatus\b|shipped|out for delivery|\bdelivered\b|where is /,
    () => ["Chasing down the delivery van…", "Asking the warehouse where it wandered off to…", "Peering down the road for your parcel…"],
  ],
  [/\bauthor\b|who wrote|\babout\b/, () => ["Reading the back cover…", "Peeking at the dust jacket…"]],
  [/recommend|suggest|what should i read/, () => ["Browsing the staff picks for you…", "Running a finger along the shelves…"]],
  [
    /^(yes|yeah|yep|sure|ok|okay|sounds good|that works|i'?ll take it|i will take it|please do)\b/,
    () => ["Stamping the paperwork…", "Filing it neatly, corners squared…"],
  ],
  [/store credit|\bvisa\b|\bcard\b|original payment/, () => ["Warming up the till…", "Peeking into the till…"]],
  [
    /^(no|nope|no thanks|never mind|bye|goodbye|that'?s all|thanks|thank you)\b/,
    () => ["Tidying the counter…", "Straightening the bookmarks…"],
  ],
  [/discount|coupon|promo|\bcode\b/, () => ["Rattling the coupon drawer…"]],
  [
    /polic|how long|how many|shipping|cancel|address|\btax\b|ebook|audiobook|\bgift\b|password|sign.?in|log.?in/,
    () => ["Checking the shop handbook…", "Flipping through the store policies…"],
  ],
  [/\breturn/, () => ["Opening the returns drawer…", "Getting a return slip ready…", "Fetching the returns ledger…"]],
]

let last = ""

function choose(lines: string[]): string {
  const fresh = lines.length > 1 ? lines.filter((line) => line !== last) : lines
  const line = fresh[Math.floor(Math.random() * fresh.length)] ?? GENERAL[0]
  last = line
  return line
}

/** A working line for this message. `shown` is the title a clicked button displayed. */
export function workingLine(message: string, shown?: string): string {
  const text = message.trim().toLowerCase()
  const article = ARTICLE_LINES[text.replace(/^faq:/, "")]
  if (article && !text.startsWith("faq:more:")) return choose(article)
  for (const [pattern, pick] of RULES) {
    if (pattern.test(text)) return choose(pick(shown?.trim() || undefined))
  }
  return choose(GENERAL)
}
