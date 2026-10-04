import { useEffect, useRef, useState } from "react"
import { Download, PhoneOff } from "lucide-react"
import { Button } from "@/components/ui/button.tsx"
import type { CustomerId, OrderChoice, ParcelLabel, ReceiptDownload, ToolTrace } from "../agent/provider.ts"
import { startVoiceCall, type VoiceReply, type VoiceSession } from "../speech/call.ts"

type CallLine =
  | { id: string; role: "mara"; text: string; step?: string; choices?: OrderChoice[]; tools?: ToolTrace[]; receipt?: ReceiptDownload; label?: ParcelLabel }
  | { id: string; role: "user"; text: string }

const STATUS: Record<string, string> = {
  starting: "Getting Mara's voice ready…",
  speaking: "Mara is talking. Speak to interrupt.",
  listening: "Listening.",
  thinking: "Checking the order book…",
}

export function CallPanel({
  customerId,
  onClose,
}: {
  customerId: CustomerId
  onClose: () => void
}) {
  const [lines, setLines] = useState<CallLine[]>([])
  const [status, setStatus] = useState("Connecting the call…")
  const [micError, setMicError] = useState<string | null>(null)
  const [deskError, setDeskError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const session = useRef<VoiceSession | null>(null)
  const scroller = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let call: VoiceSession | null = null
    const timer = window.setTimeout(() => {
      call = startVoiceCall(customerId, {
      onGreeting(text) {
        setLines((current) =>
          current.some((line) => line.role === "mara" && line.text === text)
            ? current
            : [...current, { id: "greeting", role: "mara", text }],
        )
      },
      onUser(text) {
        setBusy(true)
        setLines((current) => [...current, { id: crypto.randomUUID(), role: "user", text }])
      },
      onReply(reply: VoiceReply) {
        setBusy(false)
        setLines((current) => [
          ...current,
          {
            id: crypto.randomUUID(),
            role: "mara",
            text: reply.spoken || reply.text,
            step: reply.step,
            choices: reply.choices,
            tools: reply.tools,
            receipt: reply.receipt,
            label: reply.label,
          },
        ])
      },
      onStatus(state) {
        setStatus(STATUS[state] ?? "On the call.")
        if (state === "thinking") setBusy(true)
        if (state === "listening" || state === "speaking") setBusy(false)
      },
      onError(message) {
        setDeskError(message)
        setBusy(false)
      },
      onMicError(message) {
        setMicError(message)
      },
    })
    session.current = call
    }, 0)
    return () => {
      window.clearTimeout(timer)
      call?.stop()
      session.current = null
    }
  }, [customerId])

  useEffect(() => {
    const node = scroller.current
    if (!node) return
    node.scrollTop = node.scrollHeight
  }, [lines, micError, deskError])

  function choose(orderId: string) {
    session.current?.sendText(orderId)
  }

  return (
    <section id="mara-call" aria-label="Call with Mara" className="shrink-0 border-b border-border bg-card">
      <div className="mx-auto flex max-h-80 w-full max-w-3xl flex-col px-4 py-3 sm:max-h-96">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-serif text-xl leading-none">Call with Mara</h2>
            <p className="mt-1 text-sm text-muted-foreground" role="status">
              {status}
            </p>
          </div>
          <Button type="button" variant="outline" className="h-11 shrink-0" onClick={onClose}>
            <PhoneOff />
            End call
          </Button>
        </div>
        {micError ? (
          <p className="mt-3 text-sm text-destructive" role="alert">
            {micError}
          </p>
        ) : null}
        {deskError ? (
          <p className="mt-3 text-sm text-destructive" role="alert">
            {deskError}
          </p>
        ) : null}
        <div ref={scroller} className="mt-3 min-h-24 flex-1 space-y-3 overflow-y-auto" role="log" aria-live="polite">
          {lines.length === 0 ? (
            <p className="text-sm text-muted-foreground">Connecting the call…</p>
          ) : (
            lines.map((line) =>
              line.role === "user" ? (
                <p key={line.id} className="ml-8 rounded-2xl rounded-br-md bg-primary px-3 py-2 text-primary-foreground">
                  {line.text}
                </p>
              ) : (
                <article key={line.id} className="mr-8 rounded-2xl rounded-bl-md border border-border bg-background px-3 py-2">
                  <p className="font-serif text-sm">Mara</p>
                  {line.tools && line.tools.length > 0 ? (
                    <ul className="mt-2 space-y-1">
                      {line.tools.map((tool) => (
                        <li key={`${tool.name}-${tool.summary}`} className="rounded-md bg-secondary px-2 py-1 text-sm">
                          <span className="font-semibold">Used {tool.name}</span>
                          <span className="mt-0.5 block text-muted-foreground">{tool.summary}</span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <p className="mt-1 whitespace-pre-wrap">{line.text}</p>
                  {line.choices && line.choices.length > 0 ? (
                    <ul className="mt-2 grid gap-2" aria-label="Choose an order">
                      {line.choices.map((choice) => (
                        <li key={choice.order_id}>
                          <Button
                            type="button"
                            variant="outline"
                            disabled={busy}
                            className="h-auto min-h-11 w-full items-start justify-start whitespace-normal px-3 py-2 text-left"
                            onClick={() => choose(choice.order_id)}
                          >
                            <span className="min-w-0">
                              <span className="block font-semibold break-words">{choice.title}</span>
                              <span className="block text-xs font-normal break-words text-muted-foreground">
                                {/^BLY-\d+$/i.test(choice.order_id)
                                  ? `${choice.order_id} · ${choice.mark}`
                                  : choice.mark}
                              </span>
                            </span>
                          </Button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  {line.step ? (
                    <p className="mt-2 border-t border-border pt-2 text-sm text-muted-foreground">{line.step}</p>
                  ) : null}
                  {line.receipt || line.label ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {line.receipt ? (
                        <a
                          href={line.receipt.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex h-11 items-center gap-2 rounded-lg border border-border bg-background px-3 text-sm font-medium hover:bg-muted"
                        >
                          <Download aria-hidden="true" />
                          Open return receipt
                        </a>
                      ) : null}
                      {line.label ? (
                        <a
                          href={line.label.url}
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
                </article>
              ),
            )
          )}
        </div>
      </div>
    </section>
  )
}
