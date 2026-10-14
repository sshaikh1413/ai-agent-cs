export interface SpeechSession {
  stop: () => void
}

interface RecognitionResultLike {
  isFinal: boolean
  0?: { transcript?: string }
}

interface RecognitionEventLike {
  results: ArrayLike<RecognitionResultLike>
}

interface RecognitionErrorEventLike {
  error?: string
}

interface BrowserRecognition extends EventTarget {
  lang: string
  continuous: boolean
  interimResults: boolean
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: RecognitionEventLike) => void) | null
  onerror: ((event: RecognitionErrorEventLike) => void) | null
  onend: (() => void) | null
}

type RecognitionCtor = new () => BrowserRecognition

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null
  const host = window as Window & {
    SpeechRecognition?: RecognitionCtor
    webkitSpeechRecognition?: RecognitionCtor
  }
  return host.SpeechRecognition ?? host.webkitSpeechRecognition ?? null
}

export function speechInputSupported(): boolean {
  return recognitionCtor() !== null
}

export function startSpeechInput(options: {
  onTranscript: (transcript: string) => void
  onError: (message: string) => void
  onEnd: () => void
}): SpeechSession {
  const Ctor = recognitionCtor()
  if (!Ctor) {
    options.onError("Speech input isn't available in this browser. Typing still works.")
    options.onEnd()
    return { stop() {} }
  }

  const recognition = new Ctor()
  recognition.lang = "en-US"
  recognition.continuous = true
  recognition.interimResults = true
  let stopped = false

  recognition.onresult = (event) => {
    let transcript = ""
    for (let index = 0; index < event.results.length; index += 1) {
      transcript += event.results[index]?.[0]?.transcript ?? ""
    }
    options.onTranscript(transcript.replace(/\s+/g, " ").trim())
  }

  recognition.onerror = (event) => {
    const code = event.error ?? ""
    if (code === "aborted" || code === "no-speech") return
    stopped = true
    if (code === "not-allowed" || code === "service-not-allowed") {
      options.onError(
        "The microphone is blocked. Allow it for this site, or type your question.",
      )
      return
    }
    options.onError("Speech input stopped. You can keep typing.")
  }

  recognition.onend = () => {
    if (!stopped) {
      stopped = true
    }
    options.onEnd()
  }

  try {
    recognition.start()
  } catch {
    stopped = true
    options.onError("Speech input didn't start. You can keep typing.")
    options.onEnd()
  }

  return {
    stop() {
      stopped = true
      recognition.stop()
    },
  }
}
