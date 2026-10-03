import { useEffect, useRef, useState } from "react"
import { Mic, SendHorizontal } from "lucide-react"
import { Button } from "@/components/ui/button.tsx"
import { Textarea } from "@/components/ui/textarea.tsx"
import { speechInputSupported, startSpeechInput, type SpeechSession } from "../speech/recognition.ts"

export function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean
  onSend: (text: string) => void
}) {
  const [draft, setDraft] = useState("")
  const [listening, setListening] = useState(false)
  const [fromSpeech, setFromSpeech] = useState(false)
  const [speechError, setSpeechError] = useState<string | null>(null)
  const supported = speechInputSupported()
  const session = useRef<SpeechSession | null>(null)
  const base = useRef("")

  useEffect(() => {
    return () => session.current?.stop()
  }, [])

  function stopListening() {
    session.current?.stop()
    session.current = null
    setListening(false)
  }

  function toggleMic() {
    if (listening) {
      stopListening()
      return
    }
    setSpeechError(null)
    base.current = draft.trim()
    setListening(true)
    session.current = startSpeechInput({
      onTranscript(transcript) {
        const prefix = base.current
        setDraft(prefix ? `${prefix} ${transcript}` : transcript)
        setFromSpeech(true)
      },
      onError(message) {
        setSpeechError(message)
        setListening(false)
      },
      onEnd() {
        setListening(false)
      },
    })
  }

  function submit() {
    const text = draft.trim()
    if (!text || disabled) return
    stopListening()
    setDraft("")
    setFromSpeech(false)
    setSpeechError(null)
    onSend(text)
  }

  const label = fromSpeech ? "Speech transcript — edit it, then send" : "Message Mara"

  return (
    <form
      className="border-t border-border bg-card px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      <label htmlFor="mara-message" className="mb-2 block text-sm font-semibold text-foreground">
        {label}
      </label>
      <Textarea
        id="mara-message"
        value={draft}
        maxLength={2000}
        rows={3}
        disabled={disabled}
        placeholder="Ask where an order is, or start a return. An order number looks like BLY-10482."
        className={`min-h-24 bg-background px-3 py-3 text-base md:text-base ${listening ? "border-ring ring-3 ring-ring/40" : ""}`}
        onChange={(event) => {
          setDraft(event.target.value)
          if (!listening) setFromSpeech(false)
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            submit()
          }
        }}
      />
      <div className="mt-2 flex items-center gap-2">
        <Button
          type="button"
          variant={listening ? "default" : "outline"}
          size="icon-lg"
          className="size-11"
          disabled={!supported || disabled}
          aria-pressed={listening}
          aria-label={listening ? "Stop speech input" : "Speak your question"}
          title={
            supported
              ? "Speak, then edit the transcript before you send"
              : "Speech input isn't available in this browser"
          }
          onClick={toggleMic}
        >
          <Mic />
        </Button>
        <p className="min-w-0 flex-1 text-sm text-muted-foreground" role="status">
          {listening
            ? "Listening. The transcript lands in the box so you can edit it before sending."
            : speechError
              ? speechError
              : supported
                ? "Enter to send. Shift+Enter for a new line."
                : "Speech input isn't available in this browser. Typing still works."}
        </p>
        <Button type="submit" className="h-11 px-4" disabled={disabled || draft.trim().length === 0}>
          Send
          <SendHorizontal />
        </Button>
      </div>
    </form>
  )
}
