import { useEffect, useRef, useState } from "react"
import { BookOpen, Download, Phone, RotateCcw, Volume2, VolumeX } from "lucide-react"
import { Button } from "@/components/ui/button.tsx"
import {
  AgentDeskError,
  getAgentProvider,
  type AgentIntent,
  type AgentTurn,
  type CustomerId,
  type DeskInfo,
  type DeskOrder,
  type OrderChoice,
  type ParcelLabel,
  type ReceiptDownload,
  type ToolTrace,
} from "../agent/provider.ts"
import { speak, speechOutputSupported, stopSpeaking } from "../speech/playback.ts"
import { CallPanel } from "./CallPanel.tsx"
import { Composer } from "./Composer.tsx"

type ThreadItem =
  | { id: string; kind: "user"; text: string }
  | {
      id: string
      kind: "assistant"
      text: string
      intent: AgentIntent
      tools: ToolTrace[]
      receipt?: ReceiptDownload
      label?: ParcelLabel
      step?: string
      opening?: string
      memory?: boolean
      choices?: OrderChoice[]
    }
  | { id: string; kind: "error"; text: string; retryMessage: string }
  | { id: string; kind: "pending" }

type DeskState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; info: DeskInfo }

const provider = getAgentProvider()
const CUSTOMER_KEY = "bookly.customerId"

const READERS: { id: CustomerId; label: string; name: string }[] = [
  { id: "cust_becky", label: "Becky", name: "Becky Alvarez" },
  { id: "cust_bob", label: "Bob", name: "Bob Hale" },
]

function conversationKey(customerId: CustomerId) {
  return `bookly.conversationId.${customerId}`
}

function storedCustomer(): CustomerId {
  if (typeof sessionStorage === "undefined") return "cust_becky"
  const value = sessionStorage.getItem(CUSTOMER_KEY)
  if (value === "cust_bob" || value === "cust_becky") return value
  return "cust_becky"
}

function historyFrom(items: ThreadItem[], message: string): AgentTurn[] {
  const turns: AgentTurn[] = []
  for (const item of items) {
    if (item.kind === "user") turns.push({ role: "user", content: item.text })
    if (item.kind === "assistant") turns.push({ role: "assistant", content: item.text })
  }
  const last = turns.at(-1)
  if (last?.role === "user" && last.content === message) return turns.slice(0, -1)
  return turns
}

export function SupportDesk() {
  const [desk, setDesk] = useState<DeskState>({ status: "loading" })
  const [items, setItems] = useState<ThreadItem[]>([])
  const [busy, setBusy] = useState(false)
  const [speakingId, setSpeakingId] = useState<string | null>(null)
  const [playbackErrorId, setPlaybackErrorId] = useState<string | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const canSpeak = speechOutputSupported()
  const deskRequest = useRef(0)
  const [customerId, setCustomerId] = useState<CustomerId>(storedCustomer)
  const [resetting, setResetting] = useState(false)
  const [resetError, setResetError] = useState<string | null>(null)
  const [callOpen, setCallOpen] = useState(false)
  const customerIdRef = useRef<CustomerId>(customerId)
  const conversationId = useRef<string | null>(
    typeof sessionStorage === "undefined" ? null : sessionStorage.getItem(conversationKey(customerId)),
  )
  const locked = busy || resetting

  async function loadDesk(forCustomer: CustomerId = customerIdRef.current) {
    const requestId = deskRequest.current + 1
    deskRequest.current = requestId
    setDesk({ status: "loading" })
    try {
      const info = await provider.desk(forCustomer)
      if (deskRequest.current !== requestId || customerIdRef.current !== forCustomer) return
      setDesk({ status: "ready", info })
      if (info.opening) {
        setItems((current) =>
          current.length === 0
            ? [
                {
                  id: `opening-${forCustomer}`,
                  kind: "assistant",
                  text: info.opening as string,
                  intent: "return_refund",
                  tools: [],
                  memory: true,
                },
              ]
            : current,
        )
      }
    } catch (error) {
      if (deskRequest.current !== requestId || customerIdRef.current !== forCustomer) return
      const message = error instanceof AgentDeskError ? error.message : "The order list didn't load."
      setDesk({ status: "error", message })
    }
  }

  function endCall() {
    setCallOpen(false)
  }

  async function resetDemo() {
    if (locked) return
    endCall()
    setResetting(true)
    setResetError(null)
    stopSpeaking()
    setSpeakingId(null)
    try {
      await provider.resetDemo()
      sessionStorage.removeItem(conversationKey("cust_becky"))
      sessionStorage.removeItem(conversationKey("cust_bob"))
      conversationId.current = null
      setItems([])
      await loadDesk(customerIdRef.current)
    } catch (error) {
      const message = error instanceof AgentDeskError ? error.message : "The demo didn't reset. Try again in a moment."
      setResetError(message)
    } finally {
      setResetting(false)
    }
  }

  function signIn(next: CustomerId) {
    if (next === customerIdRef.current || locked) return
    endCall()
    stopSpeaking()
    setSpeakingId(null)
    sessionStorage.removeItem(conversationKey(next))
    conversationId.current = null
    customerIdRef.current = next
    sessionStorage.setItem(CUSTOMER_KEY, next)
    setCustomerId(next)
    setItems([])
    void loadDesk(next)
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadDesk()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [])

  useEffect(() => {
    const node = scroller.current
    if (!node) return
    node.scrollTop = node.scrollHeight
  }, [items])

  useEffect(() => {
    return () => stopSpeaking()
  }, [])

  async function run(prior: ThreadItem[], message: string, pendingId: string) {
    setBusy(true)
    stopSpeaking()
    setSpeakingId(null)
    try {
      const reply = await provider.reply({
        message,
        history: historyFrom(prior, message),
        conversation_id: conversationId.current ?? undefined,
        customer_id: customerIdRef.current,
      })
      const previousId = conversationId.current
      const hadReply = prior.some((item) => item.kind === "assistant" && !item.memory)
      const restarted = Boolean(previousId && reply.conversation_id && reply.conversation_id !== previousId)
      if (reply.conversation_id) {
        conversationId.current = reply.conversation_id
        sessionStorage.setItem(conversationKey(customerIdRef.current), reply.conversation_id)
      }
      const alreadyRemembered = prior.some(
        (item) =>
          item.kind === "assistant" &&
          ((item.memory && item.text === reply.opening) || item.opening === reply.opening),
      )
      const opening =
        reply.opening && ((restarted && hadReply) || !alreadyRemembered) ? reply.opening : undefined
      setItems((current) =>
        current
          .filter((item) => item.id !== pendingId)
          .concat({
            id: crypto.randomUUID(),
            kind: "assistant",
            text: reply.reply,
            intent: reply.intent,
            tools: reply.tools,
            receipt: reply.receipt,
            label: reply.label,
            step: reply.step,
            opening,
            choices: reply.choices,
          }),
      )
    } catch (error) {
      const text =
        error instanceof AgentDeskError
          ? error.message
          : "Mara's desk didn't answer. Nothing was filed. Try again in a moment."
      setItems((current) =>
        current
          .filter((item) => item.id !== pendingId)
          .concat({ id: crypto.randomUUID(), kind: "error", text, retryMessage: message }),
      )
    } finally {
      setBusy(false)
    }
  }

  function send(text: string) {
    const message = text.trim()
    if (!message || locked) return
    const pendingId = crypto.randomUUID()
    const prior = items
    setItems([
      ...prior,
      { id: crypto.randomUUID(), kind: "user", text: message },
      { id: pendingId, kind: "pending" },
    ])
    void run(prior, message, pendingId)
  }

  function retry(errorId: string, message: string) {
    if (locked) return
    const pendingId = crypto.randomUUID()
    const prior = items.filter((item) => item.id !== errorId)
    setItems([...prior, { id: pendingId, kind: "pending" }])
    void run(prior, message, pendingId)
  }

  function toggleSpeak(id: string, text: string) {
    if (speakingId === id) {
      stopSpeaking()
      setSpeakingId(null)
      return
    }
    setPlaybackErrorId(null)
    setSpeakingId(id)
    speak(text, {
      onend: () => setSpeakingId((current) => (current === id ? null : current)),
      onerror: () => {
        setSpeakingId((current) => (current === id ? null : current))
        setPlaybackErrorId(id)
      },
    })
  }

  const prompts = desk.status === "ready" ? desk.info.prompts : []

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <header className="min-w-0 shrink-0 bg-primary text-primary-foreground">
        <div className="mx-auto flex min-w-0 max-w-6xl items-center gap-3 px-4 py-3">
          <div className="flex min-w-0 flex-1 items-center gap-3 overflow-hidden">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-foreground/10">
              <BookOpen aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <p className="truncate font-serif text-2xl leading-none italic">Bookly</p>
              <p className="truncate text-sm text-primary-foreground/80">Support desk</p>
            </div>
          </div>
          <div className="flex shrink-0 flex-nowrap items-center gap-1 sm:gap-2">
            <Button
              type="button"
              variant="ghost"
              disabled={locked}
              className="h-11 min-h-11 shrink-0 border border-primary-foreground/40 bg-primary-foreground/10 px-2 text-primary-foreground hover:bg-primary-foreground/20 hover:text-primary-foreground sm:px-3"
              onClick={() => void resetDemo()}
            >
              <RotateCcw />
              Reset demo
            </Button>
            <Button
              type="button"
              variant="ghost"
              aria-pressed={callOpen}
              aria-label={callOpen ? "End call" : "Voice"}
              aria-controls="mara-call"
              className={
                callOpen
                  ? "h-11 min-h-11 shrink-0 border border-primary-foreground bg-primary-foreground px-2 text-primary hover:bg-primary-foreground hover:text-primary sm:px-3"
                  : "h-11 min-h-11 shrink-0 border border-primary-foreground/40 bg-primary-foreground/10 px-2 text-primary-foreground hover:bg-primary-foreground/20 hover:text-primary-foreground sm:px-3"
              }
              onClick={() => {
                stopSpeaking()
                setSpeakingId(null)
                setCallOpen((open) => !open)
              }}
            >
              <Phone />
              <span className="hidden sm:inline">{callOpen ? "End call" : "Voice"}</span>
            </Button>
            <p className="shrink-0 font-serif text-lg leading-none">Mara</p>
            <div
              role="radiogroup"
              aria-label="Signed-in reader"
              className="flex h-11 shrink-0 flex-nowrap items-stretch rounded-lg bg-primary-foreground/10"
            >
              {READERS.map((reader) => {
                const selected = customerId === reader.id
                return (
                  <Button
                    key={reader.id}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    variant="ghost"
                    disabled={locked}
                    className={
                      selected
                        ? "h-11 min-h-11 shrink-0 rounded-lg bg-primary-foreground px-2 text-primary hover:bg-primary-foreground hover:text-primary sm:px-3"
                        : "h-11 min-h-11 shrink-0 rounded-lg px-2 text-primary-foreground hover:bg-primary-foreground/15 hover:text-primary-foreground sm:px-3"
                    }
                    onClick={() => signIn(reader.id)}
                  >
                    {reader.label}
                  </Button>
                )
              })}
            </div>
          </div>
        </div>
      </header>
      {resetError ? (
        <p className="bg-destructive/10 px-4 py-2 text-center text-sm text-destructive" role="alert">
          {resetError}
        </p>
      ) : null}

      <div className="mx-auto flex min-h-0 w-full max-w-6xl flex-1">
        <aside className="hidden w-96 shrink-0 flex-col border-r border-border bg-secondary/50 lg:flex">
          <DeskPanel desk={desk} busy={locked} customerId={customerId} onRetry={() => void loadDesk()} onAsk={send} />
        </aside>
        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          {callOpen ? <CallPanel customerId={customerId} onClose={endCall} /> : null}
          <details className="shrink-0 border-b border-border lg:hidden">
            <summary className="px-4 py-3 text-sm font-semibold">Profile and orders</summary>
            <div className="max-h-96 overflow-y-auto px-4 pb-3">
              <DeskPanel desk={desk} busy={locked} customerId={customerId} onRetry={() => void loadDesk()} onAsk={send} compact />
            </div>
          </details>
          <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-4 py-5" role="log" aria-live="polite">
            {items.length === 0 || items.every((item) => item.kind === "assistant" && item.memory) ? (
              <>
                {items.length > 0 ? (
                  <ol className="mx-auto mb-6 flex max-w-3xl flex-col gap-4">
                    {items.map((item) => (
                      <li key={item.id}>
                        {item.kind === "assistant" ? (
                          <AssistantBubble
                            item={item}
                            speaking={speakingId === item.id}
                            playbackError={playbackErrorId === item.id}
                            canSpeak={canSpeak}
                            busy={locked}
                            onSpeak={() => toggleSpeak(item.id, item.text)}
                            onChoose={send}
                          />
                        ) : null}
                      </li>
                    ))}
                  </ol>
                ) : null}
                <EmptyThread
                  prompts={prompts}
                  desk={desk}
                  busy={locked}
                  onAsk={send}
                  onRetry={() => void loadDesk()}
                />
              </>
            ) : (
              <ol className="mx-auto flex max-w-3xl flex-col gap-4">
                {items.map((item) => (
                  <li key={item.id}>
                    {item.kind === "user" ? <UserBubble text={item.text} /> : null}
                    {item.kind === "assistant" ? (
                      <AssistantBubble
                        item={item}
                        speaking={speakingId === item.id}
                        playbackError={playbackErrorId === item.id}
                        canSpeak={canSpeak}
                        busy={locked}
                        onSpeak={() => toggleSpeak(item.id, item.text)}
                        onChoose={send}
                      />
                    ) : null}
                    {item.kind === "pending" ? <PendingBubble /> : null}
                    {item.kind === "error" ? (
                      <ErrorBubble text={item.text} onRetry={() => retry(item.id, item.retryMessage)} />
                    ) : null}
                  </li>
                ))}
              </ol>
            )}
          </div>
          {!canSpeak ? (
            <p className="px-4 pb-2 text-center text-xs text-muted-foreground">
              Read-aloud isn't available in this browser.
            </p>
          ) : null}
          <Composer disabled={locked} callActive={callOpen} onSend={send} />
        </main>
      </div>
    </div>
  )
}

function orderQuestion(order: DeskOrder): string {
  const status = order.summary.split(" · ")[0]?.trim().toLowerCase()
  if (status && status !== "delivered" && status !== "order") {
    return `what's the status of ${order.id}`
  }
  return `I want to return ${order.id}`
}

function DeskPanel({
  desk,
  busy,
  customerId,
  compact = false,
  onRetry,
  onAsk,
}: {
  desk: DeskState
  busy: boolean
  customerId: CustomerId
  compact?: boolean
  onRetry: () => void
  onAsk: (text: string) => void
}) {
  const signedIn =
    desk.status === "ready"
      ? desk.info.customer_name
      : READERS.find((reader) => reader.id === customerId)?.name
  const help = desk.status === "ready" ? desk.info.can_help : []
  const profile = desk.status === "ready" ? desk.info.profile : []
  return (
    <div className={compact ? "" : "flex min-h-0 flex-1 flex-col overflow-y-auto p-4"}>
      <h2 className="font-serif text-xl">Mara's profile</h2>
      {desk.status === "loading" ? (
        <p className="mt-3 text-sm text-muted-foreground">Loading Mara's profile…</p>
      ) : null}
      {profile.length > 0 ? (
        <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
          {profile.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {!compact ? (
        <>
          <h2 className="mt-6 font-serif text-xl">What Mara can help with</h2>
          {desk.status === "loading" ? (
            <p className="mt-3 text-sm text-muted-foreground">Loading what this desk can do…</p>
          ) : null}
          {help.length > 0 ? (
            <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
              {help.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
      <h2 className="mt-6 font-serif text-xl">Recent orders</h2>
      {desk.status === "loading" ? (
        <p className="mt-3 text-sm text-muted-foreground" role="status">
          Loading recent orders…
        </p>
      ) : null}
      {desk.status === "error" ? (
        <div className="mt-3">
          <p className="text-sm text-destructive">{desk.message}</p>
          <Button type="button" variant="outline" className="mt-2 h-11" onClick={onRetry}>
            <RotateCcw />
            Try again
          </Button>
        </div>
      ) : null}
      {desk.status === "ready" ? (
        <ul className="mt-3 space-y-2">
          {desk.info.sample_orders.map((order) => (
            <li key={order.id}>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                className="h-auto min-h-11 w-full justify-start whitespace-normal px-3 py-2 text-left"
                onClick={() => onAsk(orderQuestion(order))}
              >
                <span>
                  <span className="block font-semibold">{order.id}</span>
                  <span className="block text-xs font-normal text-muted-foreground">
                    {order.customer_name} · {order.summary}
                  </span>
                </span>
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="mt-4 text-xs text-muted-foreground">
        Signed in as {signedIn}. Switching readers starts a new conversation.
      </p>
    </div>
  )
}

function EmptyThread({
  prompts,
  desk,
  busy,
  onAsk,
  onRetry,
}: {
  prompts: string[]
  desk: DeskState
  busy: boolean
  onAsk: (text: string) => void
  onRetry: () => void
}) {
  const name = desk.status === "ready" ? desk.info.customer_name : null
  const first = name ? name.split(" ")[0] : null
  return (
    <div className="mx-auto max-w-2xl pt-6 sm:pt-12">
      <h1 className="font-serif text-3xl leading-tight sm:text-4xl">
        {first ? `Return a book from ${first}'s account.` : "Return a book from this account."}
      </h1>
      <p className="mt-4 text-base text-muted-foreground">
        Mara asks why the book is coming back, then refunds the card on file or store credit
        after {first ? `${first} chooses` : "you choose"}. The return is written only after that
        choice, and that turn has the PDF receipt. If the book is past the 30 days, she can
        offer store credit only, and that turn opens the receipt and a parcel label. She can
        also say where an order is, from the status stored on it.
        {name ? ` Signed in as ${name}.` : ""}
      </p>
      {desk.status === "loading" ? (
        <p className="mt-6 text-sm text-muted-foreground" role="status">
          Loading prompts…
        </p>
      ) : null}
      {desk.status === "error" ? (
        <div className="mt-6">
          <p className="text-sm text-destructive">{desk.message} You can still type a question.</p>
          <Button type="button" variant="outline" className="mt-2 h-11" onClick={onRetry}>
            <RotateCcw />
            Reload prompts
          </Button>
        </div>
      ) : null}
      {prompts.length > 0 ? (
        <ul className="mt-6 grid gap-2">
          {prompts.map((prompt) => (
            <li key={prompt}>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                className="h-auto min-h-11 w-full justify-start whitespace-normal px-3 py-2 text-left"
                onClick={() => onAsk(prompt)}
              >
                {prompt}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-3 text-primary-foreground whitespace-pre-wrap">
        {text}
      </p>
    </div>
  )
}

function AssistantBubble({
  item,
  speaking,
  playbackError,
  canSpeak,
  busy,
  onSpeak,
  onChoose,
}: {
  item: Extract<ThreadItem, { kind: "assistant" }>
  speaking: boolean
  playbackError: boolean
  canSpeak: boolean
  busy: boolean
  onSpeak: () => void
  onChoose: (orderId: string) => void
}) {
  return (
    <article className="max-w-[90%] rounded-2xl rounded-bl-md border border-border bg-card px-4 py-3" data-intent={item.intent}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="font-serif text-sm">Mara</p>
        {canSpeak ? (
          <Button type="button" variant="ghost" size="sm" className="h-9" onClick={onSpeak} aria-pressed={speaking}>
            {speaking ? <VolumeX /> : <Volume2 />}
            {speaking ? "Stop" : "Play reply"}
          </Button>
        ) : null}
      </div>
      {item.tools.length > 0 ? (
        <ul className="mb-3 space-y-1">
          {item.tools.map((tool) => (
            <li key={`${tool.name}-${tool.summary}`} className="rounded-md bg-secondary px-2.5 py-1.5 text-sm">
              <span className="font-semibold">Used {tool.name}</span>
              <span className="mt-0.5 block text-muted-foreground">{tool.summary}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {item.opening ? <p className="mb-3 whitespace-pre-wrap">{item.opening}</p> : null}
      <p className="whitespace-pre-wrap">{item.text}</p>
      {item.choices && item.choices.length > 0 ? (
        <ul
          className="mt-3 grid gap-2"
          aria-label={
            item.choices.every((choice) => !/^BLY-\d+$/i.test(choice.order_id))
              ? "Choose a topic"
              : "Choose an order"
          }
        >
          {item.choices.map((choice) => {
            const orderLike = /^BLY-\d+$/i.test(choice.order_id)
            return (
              <li key={choice.order_id}>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  className="h-auto min-h-11 w-full max-w-full items-start justify-start whitespace-normal px-3 py-2 text-left"
                  onClick={() => onChoose(choice.order_id)}
                >
                  <span className="min-w-0">
                    <span className="block font-semibold break-words">{choice.title}</span>
                    <span className="block text-xs font-normal break-words text-muted-foreground">
                      {orderLike ? `${choice.order_id} · ${choice.mark}` : choice.mark}
                    </span>
                  </span>
                </Button>
              </li>
            )
          })}
        </ul>
      ) : null}
      {item.step ? (
        <p className="mt-3 border-t border-border pt-2 text-sm text-muted-foreground">{item.step}</p>
      ) : null}
      {item.receipt || item.label ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {item.receipt ? (
            <a
              href={item.receipt.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-11 items-center gap-2 rounded-lg border border-border bg-background px-3 text-sm font-medium hover:bg-muted"
            >
              <Download aria-hidden="true" />
              Open return receipt
            </a>
          ) : null}
          {item.label ? (
            <a
              href={item.label.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-11 items-center gap-2 rounded-lg border border-border bg-background px-3 text-sm font-medium hover:bg-muted"
            >
              <Download aria-hidden="true" />
              Open parcel label
            </a>
          ) : null}
        </div>
      ) : null}
      {playbackError ? (
        <p className="mt-2 text-sm text-destructive">Playback didn't start in this browser.</p>
      ) : null}
    </article>
  )
}

function PendingBubble() {
  return (
    <p className="text-sm text-muted-foreground" role="status">
      <span className="mr-2 inline-block size-2 animate-pulse rounded-full bg-primary align-middle motion-reduce:animate-none" />
      Checking the order book…
    </p>
  )
}

function ErrorBubble({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <div className="max-w-[90%] rounded-2xl border border-destructive/40 bg-card px-4 py-3" role="alert">
      <p className="text-destructive">{text}</p>
      <Button type="button" variant="outline" className="mt-3 h-11" onClick={onRetry}>
        <RotateCcw />
        Try the same question again
      </Button>
    </div>
  )
}
