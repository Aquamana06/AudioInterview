export type WakeRecognition = {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
  start(): void
  abort(): void
}

export function wakeRecognitionConstructor(): (new () => WakeRecognition) | undefined {
  const browser = window as typeof window & {
    SpeechRecognition?: new () => WakeRecognition
    webkitSpeechRecognition?: new () => WakeRecognition
  }
  return browser.SpeechRecognition ?? browser.webkitSpeechRecognition
}

export function isWakeWord(text: string): boolean {
  const normalized = text.normalize('NFKC').toLowerCase().replace(/[\s\p{P}\p{S}]/gu, '')
  return /^(?:hey|ヘイ|ヘーイ|へい|へーい)(?:whisper|ウィスパー|ウイスパー|うぃすぱー|ういすぱー)$/.test(normalized)
}
