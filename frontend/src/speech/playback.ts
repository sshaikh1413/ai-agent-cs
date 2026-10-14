export function speechOutputSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window
}

function preferredVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices()
  return (
    voices.find(
      (voice) =>
        voice.lang.toLowerCase().startsWith("en") &&
        /natural|samantha|aria|google/i.test(voice.name),
    ) ??
    voices.find((voice) => voice.lang.toLowerCase().startsWith("en")) ??
    null
  )
}

export function stopSpeaking(): void {
  if (!speechOutputSupported()) return
  window.speechSynthesis.cancel()
}

export function speak(
  text: string,
  handlers: { onend: () => void; onerror: () => void },
): void {
  if (!speechOutputSupported()) {
    handlers.onerror()
    return
  }
  const synth = window.speechSynthesis
  synth.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = "en-US"
  utterance.rate = 1
  const voice = preferredVoice()
  if (voice) utterance.voice = voice
  utterance.onend = () => handlers.onend()
  utterance.onerror = () => handlers.onerror()
  synth.resume()
  synth.speak(utterance)
}
