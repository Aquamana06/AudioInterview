import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import QRCode from 'qrcode'
import './App.css'
import alpacaBackground from './assets/interview-alpaca-background.png'
import { api, ApiError } from './api'
import { pcmToWav, transcribeAudio } from './speech'
import { isWakeWord, wakeRecognitionConstructor } from './wakeWord'
import { clearWorkspace, readWorkspace, saveWorkspace } from './workspace'

type Language = 'ja' | 'en' | 'de'
type Role = 'admin' | 'operator'
type Account = { id: string; role: Role; displayName: string }
type Session = { id: string; account_id: string; title: string; language: Language; status: 'running' | 'ended'; started_at: string; updated_at: string; memory_status?: 'pending' | 'ready' | 'fallback' | null }
type Message = { id: string; role: 'system' | 'user'; content: string; inputMode: 'text' | 'voice' | 'system'; createdAt: string; updatedAt: string }
type InterviewState = { task_coverage: number; task_depth: number; irregular_coverage: number; turn_count: number }
type SessionPayload = { session: Session; messages: Message[]; state: InterviewState; stateLabel: 'running' | 'end'; memory: { status: 'not_started' | 'pending' | 'ready' | 'fallback'; summary: string | null } }
type SpeechState = 'ready' | 'wake' | 'recording' | 'transcribing' | 'thinking' | 'speaking' | 'ended' | 'error'

type BarcodeDetectorLike = { detect(source: ImageBitmap): Promise<Array<{ rawValue: string }>> }

const labels: Record<SpeechState, string> = {
  ready: 'Ready', wake: 'Waiting for the next question', recording: 'Recording', transcribing: 'サーバーで音声認識中',
  thinking: 'Interviewer thinking', speaking: 'Speaking', ended: 'Ended', error: 'Error',
}
const languageLabels: Record<Language, string> = { ja: '日本語', en: 'English', de: 'Deutsch' }
const locale: Record<Language, string> = { ja: 'ja-JP', en: 'en-US', de: 'de-DE' }

function jsonInit(method: string, body?: unknown): RequestInit {
  return { method, headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) }
}

function Login({ onLogin }: { onLogin: (account: Account) => void }) {
  const [mode, setMode] = useState<'id' | 'qr'>('id')
  const [id, setId] = useState('')
  const [password, setPassword] = useState('')
  const [qrToken, setQrToken] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const result = await api<{ account: Account }>('/api/auth/login', jsonInit('POST', mode === 'id' ? { id, password } : { qrToken }))
      onLogin(result.account)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'ログインできませんでした') }
    finally { setBusy(false) }
  }

  async function scanQr(file: File) {
    const win = window as typeof window & { BarcodeDetector?: new (options: { formats: string[] }) => BarcodeDetectorLike }
    if (!win.BarcodeDetector) { setError('このブラウザは画像QR読取に未対応です。QRトークンを貼り付けてください。'); return }
    try {
      const bitmap = await createImageBitmap(file); const detector = new win.BarcodeDetector({ formats: ['qr_code'] }); const values = await detector.detect(bitmap)
      if (!values[0]?.rawValue) throw new Error('QRコードを検出できませんでした')
      setQrToken(values[0].rawValue); setError('')
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'QRコードを読めませんでした') }
  }

  return <main className="login-page">
    <section className="login-card">
      <div className="brand-mark">AI</div>
      <h1>AudioInterview</h1>
      <p className="muted">現場の経験と判断を、安全に聞き取るインタビューシステム</p>
      <div className="tabs">
        <button className={mode === 'id' ? 'active' : ''} onClick={() => setMode('id')}>IDでログイン</button>
        <button className={mode === 'qr' ? 'active' : ''} onClick={() => setMode('qr')}>QRでログイン</button>
      </div>
      <form onSubmit={submit}>
        {mode === 'id' ? <>
          <label>ユーザーID<input value={id} onChange={event => setId(event.target.value)} autoFocus placeholder="発行されたID" /></label>
          <label>パスワード（管理者のみ）<input type="password" value={password} onChange={event => setPassword(event.target.value)} placeholder="operatorは入力不要" /></label>
        </> : <>
          <div className="qr-frame"><span>▦</span><p>管理者から発行されたQRの内容を読み取るか貼り付けてください</p></div>
          <label>QR画像を読み取る<input type="file" accept="image/*" capture="environment" onChange={event => { const file = event.target.files?.[0]; if (file) void scanQr(file) }} /></label>
          <label>QRログイントークン<input value={qrToken} onChange={event => setQrToken(event.target.value)} placeholder="audiointerview://login?id=..." /></label>
        </>}
        {error && <p className="error-message">{error}</p>}
        <button className="primary wide" disabled={busy}>{busy ? '確認中…' : 'ログイン'}</button>
      </form>
      <p className="login-hint">初期管理者: admin / admin</p>
    </section>
  </main>
}

function QrCode({ value }: { value: string }) {
  const [source, setSource] = useState('')
  useEffect(() => { QRCode.toDataURL(value, { width: 220, margin: 2, errorCorrectionLevel: 'M' }).then(setSource) }, [value])
  return source ? <img className="qr-code" src={source} alt={`ログインQR: ${value}`} /> : null
}

function AdminPanel({ onOpenSession }: { onOpenSession: (id: string) => void }) {
  const [accounts, setAccounts] = useState<Array<{ id: string; role: Role; display_name: string; is_active: number }>>([])
  const [histories, setHistories] = useState<Array<Session & { display_name: string; message_count: number }>>([])
  const [newId, setNewId] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [issued, setIssued] = useState<{ id: string; qrToken: string } | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    const [accountResult, historyResult] = await Promise.all([
      api<{ accounts: typeof accounts }>('/api/admin/accounts'), api<{ histories: typeof histories }>('/api/admin/histories'),
    ])
    setAccounts(accountResult.accounts); setHistories(historyResult.histories)
  }, [])
  useEffect(() => { void load() }, [load])
  async function issue(event: React.FormEvent) {
    event.preventDefault(); setNotice('')
    try {
      const result = await api<{ id: string; qrToken: string }>('/api/admin/accounts', jsonInit('POST', { id: newId || undefined, displayName }))
      setIssued(result); setNewId(''); setDisplayName(''); await load()
    } catch (caught) { setNotice(caught instanceof Error ? caught.message : '発行できませんでした') }
  }

  async function changePassword(event: React.FormEvent) {
    event.preventDefault()
    try { await api('/api/me/password', jsonInit('PUT', { password: newPassword })); setNewPassword(''); setNotice('管理者パスワードを変更しました') }
    catch (caught) { setNotice(caught instanceof Error ? caught.message : '変更できませんでした') }
  }

  return <div className="admin-grid">
    <section className="panel">
      <h2>オペレータID発行</h2>
      <form className="stack" onSubmit={issue}>
        <label>表示名<input value={displayName} onChange={event => setDisplayName(event.target.value)} placeholder="例: 製造一課 山田" /></label>
        <label>ID（空欄なら自動発行）<input value={newId} onChange={event => setNewId(event.target.value)} placeholder="operator_001" /></label>
        <button className="primary">IDを発行</button>
      </form>
      {issued && <div className="issued-card"><strong>{issued.id}</strong><QrCode value={issued.qrToken} /><code>{issued.qrToken}</code><button onClick={() => navigator.clipboard.writeText(issued.qrToken)}>トークンをコピー</button></div>}
      {notice && <p className="notice">{notice}</p>}
      <h3>管理者パスワード変更</h3>
      <form className="inline-form" onSubmit={changePassword}><input type="password" minLength={6} value={newPassword} onChange={event => setNewPassword(event.target.value)} placeholder="6文字以上" /><button>変更</button></form>
    </section>
    <section className="panel span-two">
      <h2>全インタビュー履歴</h2>
      <div className="table-wrap"><table><thead><tr><th>ユーザー</th><th>セッション</th><th>言語</th><th>状態</th><th>発話数</th><th /></tr></thead><tbody>
        {histories.map(item => <tr key={item.id}><td>{item.display_name}<small>{item.account_id}</small></td><td>{item.title}</td><td>{languageLabels[item.language]}</td><td><span className={`status-pill ${item.status}`}>{item.status}</span></td><td>{item.message_count}</td><td><button onClick={() => onOpenSession(item.id)}>開く</button></td></tr>)}
      </tbody></table></div>
    </section>
    <section className="panel span-two"><h2>発行済みアカウント</h2><div className="account-list">{accounts.map(item => <div key={item.id}><span className="avatar small">{item.display_name.slice(0, 1)}</span><span>{item.display_name}<small>{item.id}</small></span><span className="role-badge">{item.role}</span></div>)}</div></section>
  </div>
}

function SavingInterview({ sessionId, onFinished, onAuthRequired }: { sessionId: string; onFinished: () => Promise<void>; onAuthRequired: () => void }) {
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    const controller = new AbortController()
    async function check() {
      try {
        const result = await api<SessionPayload>(`/api/sessions/${sessionId}`, { signal: controller.signal }, 10_000)
        if (cancelled) return
        if (result.memory.status === 'ready' || result.memory.status === 'fallback') {
          await onFinished()
          if (!cancelled) timer = window.setTimeout(() => { void check() }, 1000)
          return
        }
        setError('')
      } catch (caught) {
        if (cancelled) return
        if (caught instanceof ApiError && caught.status === 401) { onAuthRequired(); return }
        if (caught instanceof ApiError && caught.status === 404) {
          try {
            await onFinished()
            if (!cancelled) timer = window.setTimeout(() => { void check() }, 1000)
            return
          }
          catch { if (cancelled) return }
        }
        setError('記録状況を確認できませんでした。保存済みの回答は保持されています。接続を確認して再確認してください。')
      }
      if (!cancelled) timer = window.setTimeout(() => { void check() }, 1000)
    }
    void check()
    return () => { cancelled = true; controller.abort(); window.clearTimeout(timer) }
  }, [sessionId, onFinished, onAuthRequired, retry])

  return <div className="loading saving-screen" role="status" aria-live="polite" aria-busy="true">
    <div className="thinking-dots" aria-hidden="true"><i /><i /><i /></div>
    <h2>インタビューの内容を記録しています</h2>
    <p>記録が完了すると、次のインタビューを開始できます。</p>
    {error && <><p className="error-message">{error}</p><button onClick={() => setRetry(value => value + 1)}>記録状況を再確認</button></>}
  </div>
}

function Interview({ sessionId, voiceStart, onVoiceChange, onSessionsChanged, onExit, onCompleted }: { sessionId: string; voiceStart: boolean; onVoiceChange: (enabled: boolean) => void; onSessionsChanged: () => void; onExit: () => void; onCompleted: (sessionId: string, closing: string) => void }) {
  const [payload, setPayload] = useState<SessionPayload | null>(null)
  const [text, setText] = useState('')
  const [displayOverrides, setDisplayOverrides] = useState<Record<string, string>>({})
  const [speechState, setSpeechState] = useState<SpeechState>('ready')
  const [liveTranscript, setLiveTranscript] = useState('')
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [handsFree, setHandsFree] = useState(voiceStart)
  useEffect(() => { onVoiceChange(handsFree) }, [handsFree, onVoiceChange])
  const [isRecording, setIsRecording] = useState(false)
  const [isBusy, setIsBusy] = useState(false)
  const [isFinalizing, setIsFinalizing] = useState(false)
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null)
  const [isClosing, setIsClosing] = useState(false)
  const completionSentRef = useRef(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const recordingRef = useRef(false)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const handsFreeRef = useRef(voiceStart)
  const finalizingRef = useRef(false)
  const startingRecordingRef = useRef<number | null>(null)
  const transcriptionSequenceRef = useRef(0)
  const pendingSpeechRef = useRef<{ content: string; language: Language } | null>(null)
  const startRecordingRef = useRef<() => void>(() => undefined)
  const voiceGenerationRef = useRef(0)
  const initialSpeechStartedRef = useRef(false)
  const speechGenerationRef = useRef(0)
  const busyRef = useRef(false)
  const overDetectorRef = useRef<{
    context: AudioContext
    source: MediaStreamAudioSourceNode
    processor: ScriptProcessorNode
    samples: number[]
    processing: boolean
    lastRequestAt: number
  } | null>(null)

  const speak = useCallback((value: string, language: Language) => {
    if (!globalThis.speechSynthesis || !globalThis.SpeechSynthesisUtterance) {
      setError('読み上げに対応していないため、画面のメッセージをご確認ください')
      setSpeechState('ready')
      return
    }
    const generation = ++speechGenerationRef.current
    speechSynthesis.cancel()
    setSpeechState('speaking')
    const sentences = value.match(/[^。！？.!?]+[。！？.!?]?/g)?.map(part => part.trim()).filter(Boolean)
    const parts = sentences?.length ? sentences : [value]
    parts.forEach((part, index) => {
      const utterance = new SpeechSynthesisUtterance(part); utterance.lang = locale[language]; utterance.rate = 1.2; utterance.pitch = 1.0
      utterance.onstart = () => { if (generation === speechGenerationRef.current) setSpeechState('speaking') }
      utterance.onend = () => {
        if (generation === speechGenerationRef.current && index === parts.length - 1) {
          setSpeechState('ready')
        }
      }
      utterance.onerror = () => {
        if (generation !== speechGenerationRef.current) return
        speechGenerationRef.current += 1
        speechSynthesis.cancel()
        setError('読み上げに失敗しました。画面のメッセージをご確認ください')
        setSpeechState('ready')
      }
      speechSynthesis.speak(utterance)
    })
  }, [])

  const load = useCallback(async () => {
    try {
      setError('')
      const data = await api<SessionPayload>(`/api/sessions/${sessionId}`, undefined, 10_000); setPayload(data)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'セッションを読み込めませんでした') }
  }, [sessionId])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (payload?.session.status !== 'ended' || isClosing) return
    switchToTextInput()
    setStreamingMessageId(null)
    setSpeechState('ended')
  }, [payload?.session.status, isClosing])
  useEffect(() => {
    if (!isClosing || !payload || streamingMessageId || isBusy || isFinalizing || speechState === 'speaking' || completionSentRef.current) return
    completionSentRef.current = true
    const closing = [...payload.messages].reverse().find(message => message.role === 'system')?.content ?? ''
    onCompleted(payload.session.id, closing)
  }, [isClosing, payload, streamingMessageId, isBusy, isFinalizing, speechState, onCompleted])
  useEffect(() => {
    if (!payload || initialSpeechStartedRef.current || payload.session.status === 'ended') return
    const opening = payload.messages.length === 1 && payload.messages[0].role === 'system' ? payload.messages[0] : null
    if (!opening) return
    initialSpeechStartedRef.current = true
    setDisplayOverrides(current => ({ ...current, [opening.id]: '' }))
    pendingSpeechRef.current = { content: opening.content, language: payload.session.language }
    setStreamingMessageId(opening.id)
  }, [payload])
  useEffect(() => {
    if (!streamingMessageId || !payload) return
    const message = payload.messages.find(item => item.id === streamingMessageId)
    if (!message) return
    const pendingSpeech = pendingSpeechRef.current
    pendingSpeechRef.current = null
    if (pendingSpeech) speak(pendingSpeech.content, pendingSpeech.language)
    let cursor = 0
    const timer = window.setInterval(() => {
      cursor = Math.min(message.content.length, cursor + 2)
      setDisplayOverrides(current => ({ ...current, [message.id]: message.content.slice(0, cursor) }))
      if (cursor >= message.content.length) {
        window.clearInterval(timer)
        setStreamingMessageId(null)
        if (!pendingSpeech) setSpeechState(payload.session.status === 'ended' ? 'ended' : 'ready')
      }
    }, 90)
    return () => window.clearInterval(timer)
  }, [streamingMessageId, payload, speak])
  useEffect(() => {
    // Recheck when either playback or the previous turn finishes. A one-shot
    // onend callback can arrive while finalization still prevents recording.
    if (!handsFree || (speechState !== 'ready' && speechState !== 'wake') || isBusy || isFinalizing || streamingMessageId || payload?.session.status !== 'running') return
    const timer = window.setTimeout(() => startRecordingRef.current(), 0)
    return () => window.clearTimeout(timer)
  }, [handsFree, speechState, isBusy, isFinalizing, streamingMessageId, payload?.session.status])
  useEffect(() => () => {
    handsFreeRef.current = false
    speechGenerationRef.current += 1
    globalThis.speechSynthesis?.cancel()
    voiceGenerationRef.current += 1
    transcriptionSequenceRef.current += 1
    stopOverDetector()
    const recorder = recorderRef.current
    if (recorder) {
      recorder.onstop = null
      recorder.ondataavailable = null
      if (recorder.state !== 'inactive') recorder.stop()
    }
    streamRef.current?.getTracks().forEach(track => track.stop())
  }, [])

  function stopOverDetector() {
    const detector = overDetectorRef.current
    overDetectorRef.current = null
    if (!detector) return
    detector.processor.onaudioprocess = null
    detector.processor.disconnect()
    detector.source.disconnect()
    void detector.context.close()
  }

  function startOverDetector(stream: MediaStream, language: Language) {
    stopOverDetector()
    const context = new AudioContext()
    const source = context.createMediaStreamSource(stream)
    const processor = context.createScriptProcessor(4096, 1, 1)
    const detector = { context, source, processor, samples: [] as number[], processing: false, lastRequestAt: 0 }
    overDetectorRef.current = detector
    processor.onaudioprocess = event => {
      if (overDetectorRef.current !== detector) return
      detector.samples.push(...event.inputBuffer.getChannelData(0))
      const maxSamples = Math.round(context.sampleRate * 4)
      if (detector.samples.length > maxSamples) detector.samples.splice(0, detector.samples.length - maxSamples)
      if (detector.processing || detector.samples.length < context.sampleRate * 1.2 || Date.now() - detector.lastRequestAt < 1000) return
      detector.lastRequestAt = Date.now()
      detector.processing = true
      const snapshot = new Float32Array(detector.samples)
      void transcribeAudio(pcmToWav(snapshot, context.sampleRate), language)
        .then(result => {
          if (overDetectorRef.current === detector && result.endOfTurn && recordingRef.current) {
            stopOverDetector()
            stopRecording()
          }
        })
        .catch(error => console.warn('[AudioInterview] Server end-of-turn detection failed', error))
        .finally(() => { detector.processing = false })
    }
    source.connect(processor)
    const sink = context.createGain(); sink.gain.value = 0; processor.connect(sink); sink.connect(context.destination)
    void context.resume()
  }

  function beep(frequency: number, duration = 0.16) {
    const context = new AudioContext(); const oscillator = context.createOscillator(); const gain = context.createGain()
    oscillator.frequency.value = frequency; oscillator.connect(gain); gain.connect(context.destination); oscillator.start()
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + duration); oscillator.stop(context.currentTime + duration)
  }

  async function transcribe(blob: Blob) {
    console.info('[AudioInterview][Whisper] transcription requested', {
      size: blob.size,
      type: blob.type,
    })
    if (!blob.size || !payload) {
      console.warn('[AudioInterview][Whisper] transcription skipped: empty audio blob')
      return null
    }
    const sequence = ++transcriptionSequenceRef.current
    setLiveTranscript('サーバーで音声を解析しています…')
    const result = await transcribeAudio(blob, payload.session.language)
    if (sequence === transcriptionSequenceRef.current) {
      setLiveTranscript(result.normalizedText ?? result.rawText)
    }
    return result
  }

  async function startRecording() {
    if (!handsFreeRef.current || !payload || payload.session.status === 'ended' || recordingRef.current || startingRecordingRef.current !== null || busyRef.current || finalizingRef.current) return
    const generation = voiceGenerationRef.current
    startingRecordingRef.current = generation
    try {
      setError(''); setLiveTranscript(''); finalizingRef.current = false
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!handsFreeRef.current || generation !== voiceGenerationRef.current) {
        stream.getTracks().forEach(track => track.stop())
        return
      }
      streamRef.current = stream
      const recorder = new MediaRecorder(stream); chunksRef.current = []; recorderRef.current = recorder
      recorder.ondataavailable = event => {
        if (!event.data.size) return
        chunksRef.current.push(event.data)
      }
      recorder.onstop = () => { void finishRecording(recorder.mimeType) }
      recorder.start(); recordingRef.current = true; setIsRecording(true); setSpeechState('recording'); beep(880)
      startOverDetector(stream, payload.session.language)
    } catch (caught) {
      if (generation !== voiceGenerationRef.current) return
      handsFreeRef.current = false; setHandsFree(false)
      setError(caught instanceof Error ? caught.message : 'マイクを開始できません'); setSpeechState('error')
    } finally {
      if (startingRecordingRef.current === generation) startingRecordingRef.current = null
    }
  }
  startRecordingRef.current = startRecording

  async function finishRecording(mimeType: string) {
    const generation = voiceGenerationRef.current
    recordingRef.current = false; setIsRecording(false); finalizingRef.current = true; setIsFinalizing(true)
    stopOverDetector()
    streamRef.current?.getTracks().forEach(track => track.stop()); streamRef.current = null; setSpeechState('transcribing'); beep(520, 0.3)
    try {
      const blob = new Blob(chunksRef.current, { type: mimeType || 'audio/webm' })
      console.info('[AudioInterview][Whisper] recording stopped', {
        chunks: chunksRef.current.length,
        size: blob.size,
        type: blob.type,
      })
      const result = await transcribe(blob)
      if (generation !== voiceGenerationRef.current) return
      const answer = (result?.maskedText ?? '').trim()
      if (answer) await send(answer, 'voice', result?.normalizedText ?? result?.rawText, true, result?.maskedText)
      else {
        setError('音声を認識できませんでした。もう一度、少し長めに話してください')
        setSpeechState('ready')
      }
    } catch (caught) {
      if (generation === voiceGenerationRef.current) {
        setError(caught instanceof Error ? caught.message : '音声認識に失敗しました'); setSpeechState('error')
      }
    }
    finally {
      if (generation === voiceGenerationRef.current) { recorderRef.current = null; finalizingRef.current = false; setIsFinalizing(false) }
    }
  }

  function stopRecording() {
    const recorder = recorderRef.current
    if (!recorder) return
    if (recorder.state !== 'inactive') {
      recordingRef.current = false; setIsRecording(false)
      recorder.stop()
    }
  }

  function toggleHandsFree() {
    if (handsFree) {
      if (recordingRef.current) stopRecording()
      handsFreeRef.current = false; setHandsFree(false); if (!recordingRef.current) setSpeechState('ready'); return
    }
    // Record locally and send short audio windows to the server for turn detection.
    handsFreeRef.current = true; setHandsFree(true)
    if (speechState !== 'speaking' && speechState !== 'thinking') setSpeechState('wake')
  }

  function switchToTextInput() {
    handsFreeRef.current = false; setHandsFree(false)
    speechGenerationRef.current += 1
    globalThis.speechSynthesis?.cancel()
    pendingSpeechRef.current = null
    voiceGenerationRef.current += 1
    startingRecordingRef.current = null
    transcriptionSequenceRef.current += 1
    stopOverDetector()
    const recorder = recorderRef.current
    if (recorder) {
      recorder.onstop = null
      recorder.ondataavailable = null
      if (recorder.state !== 'inactive') recorder.stop()
    }
    recorderRef.current = null
    streamRef.current?.getTracks().forEach(track => track.stop()); streamRef.current = null
    recordingRef.current = false; setIsRecording(false)
    finalizingRef.current = false; setIsFinalizing(false); setLiveTranscript('')
    if (!busyRef.current) setSpeechState('ready')
  }

  async function send(content: string, inputMode: 'text' | 'voice', displayText?: string, manageBusy = true, preparedMaskedText?: string) {
    if (!payload || !content.trim() || (manageBusy && busyRef.current)) return
    if (manageBusy) { busyRef.current = true; setIsBusy(true) }
    setSpeechState('thinking'); setError('')
    try {
      const beforeIds = new Set(payload.messages.map(message => message.id))
      const prepared = preparedMaskedText
        ? { maskedText: preparedMaskedText }
        : await api<{ normalizedText: string; maskedText: string }>('/api/local/mask-text', jsonInit('POST', { text: content }))
      const result = await api<SessionPayload>(`/api/sessions/${payload.session.id}/messages`, jsonInit('POST', { maskedText: prepared.maskedText, inputMode, editMessageId: editingId || undefined }))
      if (result.session.status === 'ended') {
        presentClosing(result)
        return
      }
      const newUser = result.messages.find(message => message.role === 'user' && !beforeIds.has(message.id))
      if (newUser && displayText) setDisplayOverrides(current => ({ ...current, [newUser.id]: displayText }))
      setPayload(result); setText(''); setEditingId(null); onSessionsChanged()
      const assistant = [...result.messages].reverse().find(message => message.role === 'system')
      if (assistant) {
        setDisplayOverrides(current => ({ ...current, [assistant.id]: '' }))
        pendingSpeechRef.current = handsFreeRef.current
          ? { content: assistant.content, language: result.session.language }
          : null
        setStreamingMessageId(assistant.id)
      } else setSpeechState('ready')
    } catch (caught) { setError(caught instanceof Error ? caught.message : '送信できませんでした'); setSpeechState('error') }
    finally { if (manageBusy) { busyRef.current = false; setIsBusy(false) } }
  }

  async function sendText() {
    if (!text.trim() || busyRef.current) return
    await send(text, 'text')
  }

  async function endInterview() {
    if (!payload || busyRef.current || isClosing) return
    switchToTextInput()
    busyRef.current = true; setIsBusy(true); setError('')
    try {
      const result = await api<SessionPayload>(`/api/sessions/${payload.session.id}/end`, { method: 'POST' })
      presentClosing(result)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '終了処理に失敗しました') }
    finally { busyRef.current = false; setIsBusy(false) }
  }

  function presentClosing(result: SessionPayload) {
    switchToTextInput()
    setIsClosing(true)
    setPayload(result); setText(''); setEditingId(null)
    const ending = [...result.messages].reverse().find(message => message.role === 'system')
    if (ending) {
      setDisplayOverrides(current => ({ ...current, [ending.id]: '' }))
      pendingSpeechRef.current = { content: ending.content, language: result.session.language }
      setStreamingMessageId(ending.id)
    }
  }

  if (!payload) return <div className="loading">{error ? <>
    <p role="alert">{error}</p>
    <button onClick={() => void load()}>再試行</button>
    <button onClick={onExit}>待受に戻る</button>
  </> : 'セッションを読み込んでいます…'}</div>
  const latestQuestion = [...payload.messages].reverse().find(message => message.role === 'system')
  const isThinking = speechState === 'thinking' && !streamingMessageId
  const interviewerIsActive = speechState === 'speaking' || isThinking || Boolean(streamingMessageId)
  const userIsActive = speechState === 'recording' || speechState === 'transcribing'
  return <section className={`interview-layout ${interviewerIsActive ? 'interviewer-active' : ''} ${userIsActive ? 'user-active' : ''}`}>
    <div className="interview-scene alpaca-background" style={{ backgroundImage: `url(${alpacaBackground})` }} aria-hidden="true"><div className="scene-shade" /></div>
    <header className="interview-header"><div className={`speech-status ${speechState}`}><i />{isClosing ? '終了のご挨拶' : isThinking ? 'インタビュアーが考え中…' : labels[speechState]}</div><button className="danger-outline" onClick={payload.session.status === 'ended' ? onExit : endInterview} disabled={isClosing || isBusy}>{payload.session.status === 'ended' ? '待受に戻る' : 'インタビューを終了'}</button></header>
    <div className="interview-stage">
      <div className={`assistant-bubble ${isThinking ? 'thinking' : ''}`} aria-live="polite">
        <span>interviewer</span>
        {isThinking ? <div className="thinking-dots"><i /><i /><i /></div> : <p>{latestQuestion ? (displayOverrides[latestQuestion.id] ?? latestQuestion.content) : 'よろしくお願いします。'}</p>}
      </div>
    </div>
    {liveTranscript && <div className="live-strip"><span><b>Whisper</b>{liveTranscript}</span></div>}
    <footer className="composer">
      {editingId && <div className="editing-banner">過去の回答を編集中。この時点以降を再生成します。<button onClick={() => { setEditingId(null); setText('') }}>取消</button></div>}
      {error && <p className="error-message composer-error">{error}</p>}
      <textarea id="answer" aria-label="テキストで回答" value={text} onChange={event => setText(event.target.value)} onFocus={() => { if (!isClosing) switchToTextInput() }} onKeyDown={event => {
        const nativeEvent = event.nativeEvent as KeyboardEvent
        if (event.key === 'Enter' && !event.shiftKey && !nativeEvent.isComposing && nativeEvent.keyCode !== 229) { event.preventDefault(); void sendText() }
      }} placeholder={payload.session.status === 'ended' ? 'このインタビューは終了しました' : '回答を入力（変換中はEnterで確定／確定後Enterで送信）'} disabled={payload.session.status === 'ended' || isBusy} />
      <div className="composer-actions minimal-actions">
        <button className={`handsfree-button ${handsFree ? 'active' : ''}`} onClick={toggleHandsFree} disabled={payload.session.status === 'ended' || isBusy}>{handsFree ? (isRecording ? '録音中（停止して送信）' : '自動録音中（停止）') : '音声で回答する'}</button>
        <button className="primary send" onClick={() => void sendText()} disabled={!text.trim() || payload.session.status === 'ended' || isBusy}>{isBusy ? '送信中…' : '送信'}</button>
      </div>
      {handsFree && <p className="voice-help">回答の最後に「どうぞ」または「オーバー」と話してください。</p>}
    </footer>
  </section>
}

function InterviewStandby({ disabled, starting, savingSessionId, closing, language, onStart, onFinished, onAuthRequired, controls }: {
  disabled: boolean; starting: boolean; savingSessionId: string | null; closing: string; language: Language
  onStart: (voice?: boolean) => void; onFinished: () => Promise<void>
  controls: ReactNode
  onAuthRequired: () => void
}) {
  const [wakeStatus, setWakeStatus] = useState('呼びかけを待っています')
  const [retry, setRetry] = useState(0)
  const [wakeFailed, setWakeFailed] = useState(false)
  const startRef = useRef(onStart)
  startRef.current = onStart
  useEffect(() => {
    if (disabled) return
    const Recognition = wakeRecognitionConstructor()
    if (!Recognition) { setWakeStatus('音声での開始はこのブラウザに未対応です。開始ボタンをご利用ください。'); return }
    const recognition = new Recognition()
    let stopped = false
    let timer: number | undefined
    recognition.lang = locale[language]
    recognition.continuous = true
    recognition.interimResults = false
    function start() {
      if (stopped) return
      try { recognition.start(); setWakeFailed(false); setWakeStatus('「ヘイウィスパー」と呼びかけてください') }
      catch { stopped = true; setWakeFailed(true); setWakeStatus('音声待受を開始できませんでした。音声待受を再開するか、開始ボタンをご利用ください。') }
    }
    recognition.onresult = event => {
      if (stopped) return
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal && isWakeWord(event.results[i][0].transcript)) {
          stopped = true
          recognition.abort()
          startRef.current(true)
          return
        }
      }
    }
    recognition.onerror = event => {
      if (stopped || event.error === 'no-speech') return
      stopped = true
      recognition.abort()
      setWakeFailed(true)
      setWakeStatus(event.error === 'not-allowed' || event.error === 'service-not-allowed'
        ? '音声待受にはマイクの許可が必要です。許可後に音声待受を再開できます。'
        : '音声待受が停止しました。音声待受を再開するか、開始ボタンをご利用ください。')
    }
    recognition.onend = () => { if (!stopped) timer = window.setTimeout(start, 500) }
    start()
    return () => { stopped = true; window.clearTimeout(timer); recognition.onresult = null; recognition.onerror = null; recognition.onend = null; recognition.abort() }
  }, [disabled, language, retry])

  return <section className="interview-layout standby">
    <div className="interview-scene alpaca-background" style={{ backgroundImage: `url(${alpacaBackground})` }} aria-hidden="true" />
    <header className="interview-header"><div className="speech-status"><i />{savingSessionId ? '記録中' : starting ? '準備中' : '開始待ち'}</div></header>
    <div className="interview-stage">
      <div className="assistant-bubble" aria-live="polite"><span>interviewer</span><p>{closing || 'こんにちは。「ヘイウィスパー」と呼びかけるか、開始ボタンを押してください。'}</p></div>
      {closing && <p className="session-boundary">このインタビューは終了しました</p>}
      {savingSessionId && <SavingInterview sessionId={savingSessionId} onFinished={onFinished} onAuthRequired={onAuthRequired} />}
    </div>
    <footer className="composer">
      <p className="voice-help" role="status">{starting ? 'インタビューを準備しています…' : savingSessionId ? '記録が完了するまでお待ちください。' : disabled ? '準備しています…' : wakeStatus}</p>
      {wakeFailed && !disabled && <button onClick={() => setRetry(value => value + 1)}>音声待受を再開</button>}
      <button className="primary start-interview" disabled={disabled} onClick={() => onStart(false)}>インタビューを開始</button>
      {controls}
    </footer>
  </section>
}

function App() {
  const [account, setAccount] = useState<Account | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [view, setView] = useState<'interview' | 'admin'>('interview')
  const [language, setLanguage] = useState<Language>('ja')
  const [authChecked, setAuthChecked] = useState(false)
  const [authError, setAuthError] = useState('')
  const [authAttempt, setAuthAttempt] = useState(0)
  const [sessionsError, setSessionsError] = useState('')
  const [sessionsLoaded, setSessionsLoaded] = useState(false)
  const [isStarting, setIsStarting] = useState(false)
  const [savingSessionId, setSavingSessionId] = useState<string | null>(null)
  const [startError, setStartError] = useState('')
  const [closingMessage, setClosingMessage] = useState('')
  const [voiceStart, setVoiceStart] = useState(false)
  const initialSessionResolved = useRef(false)
  const startingSessionRef = useRef(false)
  const pendingStartRef = useRef<string | null>(null)
  const restoredSessionRef = useRef<string | null>(null)

  const checkAuthentication = useCallback(() => { setAuthChecked(false); setAuthError(''); setAuthAttempt(value => value + 1) }, [])

  const loadSessions = useCallback(async () => {
    try {
      const result = await api<{ sessions: Session[] }>('/api/sessions', undefined, 10_000)
      setSessions(result.sessions)
      setSessionsError(''); setSessionsLoaded(true)
      if (!initialSessionResolved.current) {
        initialSessionResolved.current = true
        const pending = result.sessions.find(item => item.account_id === account?.id && item.status === 'ended' && item.memory_status === 'pending')
        if (pending) setSavingSessionId(pending.id)
        if (restoredSessionRef.current && !result.sessions.some(item => item.id === restoredSessionRef.current)) setSelectedId(null)
      }
      return result.sessions
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) checkAuthentication()
      else setSessionsError('セッション一覧を確認できませんでした。接続を確認して再試行してください。')
    }
  }, [account?.id, checkAuthentication])
  const exitInterview = useCallback(() => { setSelectedId(null); setView('interview') }, [])
  const completeInterview = useCallback((id: string, closing: string) => { setClosingMessage(closing); setSavingSessionId(id); setSelectedId(null) }, [])
  const finishSaving = useCallback(async () => {
    const updated = await loadSessions()
    // Refresh before enabling creation, including any older pending session.
    if (!updated) throw new Error('セッション一覧を確認できませんでした')
    const pending = updated.find(item => item.account_id === account?.id && item.status === 'ended' && item.memory_status === 'pending')
    setSavingSessionId(pending?.id ?? null)
    if (!pending) exitInterview()
  }, [account?.id, loadSessions, exitInterview])
  const acceptAccount = useCallback((value: Account, restore = false) => {
    const saved = restore ? readWorkspace(value.id) : null
    initialSessionResolved.current = false
    restoredSessionRef.current = saved?.sessionId ?? null
    pendingStartRef.current = saved?.pendingStartId ?? null
    setAccount(value)
    setSelectedId(saved?.sessionId ?? null)
    setVoiceStart(saved?.voice ?? false)
    setLanguage(saved?.language ?? 'ja')
    setSessionsLoaded(false); setSavingSessionId(null); setSessionsError('')
    setView(value.role === 'admin' ? saved?.view ?? 'admin' : 'interview')
    setAuthError('')
    setAuthChecked(true)
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    api<{ account: Account }>('/api/me', { signal: controller.signal }, 10_000)
      .then(result => { if (!controller.signal.aborted) acceptAccount(result.account, true) })
      .catch(caught => {
        if (controller.signal.aborted) return
        if (caught instanceof ApiError && caught.status === 401) { setAccount(null); setAuthChecked(true) }
        else setAuthError('ログイン状態を確認できませんでした。サーバーへの接続を確認して再試行してください。')
      })
    return () => controller.abort()
  }, [acceptAccount, authAttempt])
  useEffect(() => { if (account) void loadSessions() }, [account, loadSessions])
  useEffect(() => {
    if (!account || !sessionsLoaded) return
    saveWorkspace(account.id, { sessionId: selectedId, view, language, voice: voiceStart, pendingStartId: pendingStartRef.current })
  }, [account, sessionsLoaded, selectedId, view, language, voiceStart, isStarting])

  async function createSession(voice = false) {
    if (!account || startingSessionRef.current || savingSessionId || !sessionsLoaded || (selectedId && sessions.some(item => item.id === selectedId && item.status === 'running'))) return
    startingSessionRef.current = true
    setVoiceStart(voice)
    setIsStarting(true); setStartError('')
    try {
      if (!pendingStartRef.current) {
        const result = await api<SessionPayload>('/api/sessions', jsonInit('POST', { language }))
        pendingStartRef.current = result.session.id
        saveWorkspace(account.id, { sessionId: selectedId, view, language, voice, pendingStartId: result.session.id })
      }
      const id = pendingStartRef.current
      await api(`/api/sessions/${id}/start`, { method: 'POST' })
      pendingStartRef.current = null
      setClosingMessage(''); setSelectedId(id); setView('interview')
      await loadSessions()
    } catch (caught) {
      setStartError(caught instanceof Error ? caught.message : 'インタビューを開始できませんでした')
    } finally {
      startingSessionRef.current = false
      setIsStarting(false)
    }
  }
  async function signOut() { await api('/api/auth/logout', { method: 'POST' }); if (account) clearWorkspace(account.id); setAccount(null); setSessions([]); setSelectedId(null); setSavingSessionId(null); setClosingMessage(''); setVoiceStart(false); setSessionsLoaded(false); setStartError(''); pendingStartRef.current = null; initialSessionResolved.current = false }
  if (!authChecked) return <div className="loading" role="status">{authError ? <><p role="alert">{authError}</p><button onClick={checkAuthentication}>接続を再確認</button></> : 'AudioInterviewを準備しています…'}</div>
  if (!account) return <Login onLogin={acceptAccount} />

  const inInterview = view === 'interview'
  const navigationLocked = isStarting || Boolean(savingSessionId) || !sessionsLoaded
  const standbyControls = <details className="standby-settings"><summary>設定・履歴</summary>
    <p>{account.displayName}</p>
    <label>言語<select aria-label="インタビューの言語" value={language} onChange={event => setLanguage(event.target.value as Language)} disabled={navigationLocked}>{Object.entries(languageLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <label>セッション履歴<select aria-label="セッション履歴" value="" disabled={navigationLocked} onChange={event => { if (event.target.value) { setVoiceStart(false); setSelectedId(event.target.value); setView('interview') } }}><option value="">履歴を選択</option>{sessions.map(item => <option key={item.id} value={item.id}>{item.title} · {item.status}</option>)}</select></label>
    {account.role === 'admin' && <button onClick={() => setView('admin')} disabled={navigationLocked}>ID発行・管理画面</button>}
    <button onClick={signOut} disabled={navigationLocked}>ログアウト</button>
  </details>
  return <div className={`app-shell ${inInterview ? 'interview-app' : ''}`}>
    <aside className="sidebar"><div className="sidebar-brand"><span>AI</span><strong>AudioInterview</strong></div><button onClick={() => setView('interview')} disabled={navigationLocked}>インタビュー画面</button>{account.role === 'admin' && <button className={`admin-entry ${view === 'admin' ? 'selected' : ''}`} onClick={() => setView('admin')} disabled={navigationLocked}>⚙ ID発行・管理画面</button>}<button className="new-session" onClick={() => { setView('interview'); void createSession() }} disabled={navigationLocked || Boolean(selectedId && sessions.some(item => item.id === selectedId && item.status === 'running'))}>{isStarting ? 'インタビューを準備中…' : savingSessionId ? 'インタビューを記録中…' : '＋ 新しいインタビュー'}</button><label className="language-picker">言語<select value={language} onChange={event => setLanguage(event.target.value as Language)} disabled={navigationLocked}>{Object.entries(languageLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <nav><p>セッション</p>{sessions.map(item => <button key={item.id} className={selectedId === item.id && view === 'interview' ? 'selected' : ''} onClick={() => { setSelectedId(item.id); setView('interview') }} disabled={navigationLocked}><span>{item.title}</span><small>{languageLabels[item.language]} · {item.status}</small></button>)}</nav>
      <div className="sidebar-bottom"><div className="account-chip"><span className="avatar small">{account.displayName.slice(0, 1)}</span><div><strong>{account.displayName}</strong><small>{account.id}</small></div><button title="ログアウト" onClick={signOut} disabled={navigationLocked}>↪</button></div></div>
    </aside>
    <main className="workspace">{sessionsError && <div className="connection-error" role="alert"><p>{sessionsError}</p><button onClick={() => void loadSessions()}>セッション一覧を再確認</button></div>}{startError && <p className="error-message" role="alert">{startError}</p>}{view === 'admin' && !savingSessionId ? <AdminPanel onOpenSession={id => { setSelectedId(id); setView('interview') }} /> : selectedId && sessionsLoaded && !savingSessionId ? <Interview key={selectedId} sessionId={selectedId} voiceStart={voiceStart} onVoiceChange={setVoiceStart} onSessionsChanged={loadSessions} onExit={exitInterview} onCompleted={completeInterview} /> : <InterviewStandby disabled={navigationLocked} starting={isStarting} savingSessionId={savingSessionId} closing={closingMessage} language={language} onStart={createSession} onFinished={finishSaving} onAuthRequired={checkAuthentication} controls={standbyControls} />}</main>
  </div>
}

export default App
