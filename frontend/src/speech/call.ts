import type { CustomerId, OrderChoice, ParcelLabel, ReceiptDownload, ToolTrace } from "../agent/provider.ts"

export interface VoiceReply {
  text: string
  spoken: string
  step: string
  choices: OrderChoice[]
  tools: ToolTrace[]
  receipt?: ReceiptDownload
  label?: ParcelLabel
}

export interface VoiceSession {
  sendText: (text: string) => void
  stop: () => void
}

interface CallHandlers {
  onGreeting: (text: string) => void
  onUser: (text: string) => void
  onReply: (reply: VoiceReply) => void
  onStatus: (state: string) => void
  onError: (message: string) => void
  onMicError: (message: string) => void
}

const MIC_BLOCKED = "The microphone is blocked. Allow it for this site, or type your question."

export function startVoiceCall(customerId: CustomerId, handlers: CallHandlers): VoiceSession {
  let stopped = false
  let socketOpen = false
  let sampleRate = 22050
  const queued: string[] = []
  let ws: WebSocket | null = null
  let context: AudioContext | null = null
  let player: PcmPlayer | null = null
  let stream: MediaStream | null = null
  let processor: ScriptProcessorNode | null = null

  function stop() {
    if (stopped) return
    stopped = true
    try {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "stop" }))
      }
    } catch {
      // The socket is already gone.
    }
    ws?.close()
    ws = null
    player?.stop()
    processor?.disconnect()
    processor = null
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
    void context?.close()
    context = null
  }

  function sendText(text: string) {
    const cleaned = text.trim()
    if (!cleaned || stopped) return
    const payload = JSON.stringify({ type: "text", text: cleaned })
    if (ws && socketOpen) ws.send(payload)
    else queued.push(cleaned)
  }

  function pumpMic() {
    if (!context || !stream || stopped || processor) return
    const source = context.createMediaStreamSource(stream)
    const node = context.createScriptProcessor(4096, 1, 1)
    const mute = context.createGain()
    mute.gain.value = 0
    node.onaudioprocess = (event) => {
      if (!ws || ws.readyState !== WebSocket.OPEN || !context) return
      const input = event.inputBuffer.getChannelData(0)
      const pcm = floatToPcm16(resample(input, context.sampleRate, 16000))
      if (pcm.byteLength > 0) ws.send(pcm)
    }
    source.connect(node)
    node.connect(mute)
    mute.connect(context.destination)
    processor = node
  }

  void openMicrophone()
    .then((opened) => {
      if (stopped) {
        opened.stream.getTracks().forEach((track) => track.stop())
        void opened.context.close()
        return
      }
      context = opened.context
      player = new PcmPlayer(opened.context)
      stream = opened.stream
      pumpMic()
    })
    .catch((error: unknown) => {
      if (stopped) return
      handlers.onMicError(micMessage(error))
    })

  ws = new WebSocket(voiceUrl())
  ws.binaryType = "arraybuffer"
  ws.onopen = () => {
    if (stopped || !ws) return
    socketOpen = true
    ws.send(JSON.stringify({ type: "start", customer_id: customerId }))
    for (const text of queued.splice(0)) {
      ws.send(JSON.stringify({ type: "text", text }))
    }
  }
  ws.onmessage = (event) => {
    if (stopped) return
    if (event.data instanceof ArrayBuffer) {
      player?.play(new Int16Array(event.data), sampleRate)
      return
    }
    const message = readMessage(event.data)
    if (!message) return
    if (message.type === "greeting" && typeof message.text === "string") {
      handlers.onGreeting(message.text)
      return
    }
    if (message.type === "transcript" && message.role === "user" && typeof message.text === "string") {
      handlers.onUser(message.text)
      return
    }
    if (message.type === "reply") {
      handlers.onReply(readReply(message))
      return
    }
    if (message.type === "status" && typeof message.state === "string") {
      handlers.onStatus(message.state)
      return
    }
    if (message.type === "audio_start" && typeof message.sample_rate === "number") {
      sampleRate = message.sample_rate
      player?.stop()
      handlers.onStatus("speaking")
      return
    }
    if (message.type === "barge_in" || message.type === "audio_stop") {
      player?.stop()
      return
    }
    if (message.type === "error" && typeof message.message === "string") {
      handlers.onError(message.message)
    }
  }
  ws.onerror = () => {
    if (!stopped) handlers.onError("The call didn't connect. You can keep typing.")
  }
  ws.onclose = () => {
    socketOpen = false
  }

  return { sendText, stop }
}

function voiceUrl(): string {
  const configured = import.meta.env.VITE_AGENT_BASE_URL
  if (typeof configured === "string" && configured.trim()) {
    const url = new URL(configured.trim(), window.location.href)
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:"
    url.pathname = `${url.pathname.replace(/\/$/, "")}/api/voice`
    url.search = ""
    url.hash = ""
    return url.toString()
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${protocol}//${window.location.host}/api/voice`
}

async function openMicrophone(): Promise<{ context: AudioContext; stream: MediaStream }> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error("unsupported")
  }
  const context = new AudioContext()
  await context.resume()
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })
    return { context, stream }
  } catch (error) {
    await context.close()
    throw error
  }
}

function micMessage(error: unknown): string {
  const name = error instanceof DOMException ? error.name : ""
  if (name === "NotAllowedError" || name === "SecurityError" || name === "NotFoundError") {
    return MIC_BLOCKED
  }
  if (error instanceof Error && error.message === "unsupported") {
    return MIC_BLOCKED
  }
  return MIC_BLOCKED
}

function readMessage(data: unknown): Record<string, unknown> | null {
  if (typeof data !== "string") return null
  try {
    const parsed = JSON.parse(data) as unknown
    if (typeof parsed === "object" && parsed !== null) return parsed as Record<string, unknown>
  } catch {
    return null
  }
  return null
}

function readReply(message: Record<string, unknown>): VoiceReply {
  const text = typeof message.text === "string" ? message.text : ""
  const spoken = typeof message.spoken === "string" && message.spoken.trim() ? message.spoken : text
  const step = typeof message.step === "string" ? message.step : ""
  return {
    text,
    spoken,
    step,
    choices: readChoices(message.choices),
    tools: readTools(message.tools),
    receipt: readReceipt(message.receipt),
    label: readLabel(message.label),
  }
}

function readChoices(value: unknown): OrderChoice[] {
  if (!Array.isArray(value)) return []
  const choices: OrderChoice[] = []
  for (const item of value) {
    if (typeof item !== "object" || item === null) continue
    const record = item as Record<string, unknown>
    if (
      typeof record.order_id !== "string" ||
      typeof record.title !== "string" ||
      typeof record.mark !== "string"
    ) {
      continue
    }
    choices.push({
      order_id: record.order_id,
      title: record.title,
      mark: record.mark,
    })
  }
  return choices
}

function readTools(value: unknown): ToolTrace[] {
  if (!Array.isArray(value)) return []
  const tools: ToolTrace[] = []
  for (const item of value) {
    if (typeof item !== "object" || item === null) continue
    const record = item as Record<string, unknown>
    if (typeof record.name !== "string" || typeof record.summary !== "string") continue
    tools.push({ name: record.name as ToolTrace["name"], summary: record.summary })
  }
  return tools
}

function readReceipt(value: unknown): ReceiptDownload | undefined {
  if (typeof value !== "object" || value === null) return undefined
  const record = value as Record<string, unknown>
  if (typeof record.receipt_id !== "string" || typeof record.url !== "string") return undefined
  return { receipt_id: record.receipt_id, url: record.url }
}

function readLabel(value: unknown): ParcelLabel | undefined {
  if (typeof value !== "object" || value === null) return undefined
  const record = value as Record<string, unknown>
  if (typeof record.label_id !== "string" || typeof record.url !== "string") return undefined
  return { label_id: record.label_id, url: record.url }
}

function resample(input: Float32Array, from: number, to: number): Float32Array {
  if (from === to) return input
  const ratio = from / to
  const length = Math.max(0, Math.floor(input.length / ratio))
  const out = new Float32Array(length)
  for (let index = 0; index < length; index += 1) {
    const position = index * ratio
    const left = Math.floor(position)
    const fraction = position - left
    const a = input[left] ?? 0
    const b = input[left + 1] ?? a
    out[index] = a + (b - a) * fraction
  }
  return out
}

function floatToPcm16(input: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(input.length * 2)
  const view = new DataView(buffer)
  for (let index = 0; index < input.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, input[index] ?? 0))
    view.setInt16(index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true)
  }
  return buffer
}

class PcmPlayer {
  private next = 0
  private sources: AudioBufferSourceNode[] = []
  private context: AudioContext

  constructor(context: AudioContext) {
    this.context = context
  }

  play(pcm: Int16Array, sampleRate: number) {
    if (pcm.length === 0) return
    const audio = this.context.createBuffer(1, pcm.length, sampleRate)
    const channel = audio.getChannelData(0)
    for (let index = 0; index < pcm.length; index += 1) {
      channel[index] = (pcm[index] ?? 0) / 32768
    }
    const source = this.context.createBufferSource()
    source.buffer = audio
    source.connect(this.context.destination)
    const start = Math.max(this.context.currentTime + 0.02, this.next)
    source.start(start)
    this.next = start + audio.duration
    this.sources.push(source)
    source.onended = () => {
      this.sources = this.sources.filter((item) => item !== source)
    }
  }

  stop() {
    for (const source of this.sources) {
      try {
        source.stop()
      } catch {
        // Already stopped.
      }
    }
    this.sources = []
    this.next = 0
  }
}
