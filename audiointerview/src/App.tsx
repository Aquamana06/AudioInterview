import { useCallback, useEffect, useRef, useState } from 'react'
import QRCode from 'qrcode'
import './App.css'
import alpacaBackground from './assets/interview-alpaca-background.png'
import { detectOverInBrowser, preloadBrowserWhisper, transcribeInBrowser } from './browserWhisper'
import { prepareLocalTranscript } from './terminology'

type Language = 'ja' | 'en' | 'de'
type Role = 'admin' | 'operator'
type Account = { id: string; role: Role; displayName: string }
type Session = { id: string; account_id: string; title: string; language: Language; status: 'running' | 'ended'; started_at: string; updated_at: string }
type Message = { id: string; role: 'system' | 'user'; content: string; inputMode: 'text' | 'voice' | 'system'; createdAt: string; updatedAt: string }
type InterviewState = { task_coverage: number; task_depth: number; irregular_coverage: number; turn_count: number }
type SessionPayload = { session: Session; messages: Message[]; state: InterviewState; stateLabel: 'running' | 'end' }
type SpeechState = 'ready' | 'wake' | 'recording' | 'transcribing' | 'thinking' | 'speaking' | 'ended' | 'error'

type BarcodeDetectorLike = { detect(source: ImageBitmap): Promise<Array<{ rawValue: string }>> }
type SpeechRecognitionEventLike = { results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }>; resultIndex: number }
type SpeechRecognitionLike = {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onend: (() => void) | null
  onerror: (() => void) | null
  start(): void
  stop(): void
}

const labels: Record<SpeechState, string> = {
  ready: 'Ready', wake: 'Waiting for the next question', recording: 'Recording', transcribing: 'Local Whisper transcribing',
  thinking: 'Interviewer thinking', speaking: 'Speaking', ended: 'Ended', error: 'Error',
}
const languageLabels: Record<Language, string> = { ja: '日本語', en: 'English', de: 'Deutsch' }
const locale: Record<Language, string> = { ja: 'ja-JP', en: 'en-US', de: 'de-DE' }

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 90_000)
  const response = await fetch(path, { ...init, signal: init?.signal ?? controller.signal })
  window.clearTimeout(timeout)
  const data = await response.json().catch(() => ({})) as T & { error?: string }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`)
  return data
}

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

function Interview({ sessionId, onSessionsChanged, onExit }: { sessionId: string; onSessionsChanged: () => void; onExit: () => void }) {
  const [payload, setPayload] = useState<SessionPayload | null>(null)
  const [text, setText] = useState('')
  const [displayOverrides, setDisplayOverrides] = useState<Record<string, string>>({})
  const [speechState, setSpeechState] = useState<SpeechState>('ready')
  const [liveTranscript, setLiveTranscript] = useState('')
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [handsFree, setHandsFree] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [isBusy, setIsBusy] = useState(false)
  const [whisperReady, setWhisperReady] = useState(false)
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const recordingRef = useRef(false)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const handsFreeRef = useRef(false)
  const commandTranscriptRef = useRef('')
  const finalizingRef = useRef(false)
  const transcriptionSequenceRef = useRef(0)
  const pendingSpeechRef = useRef<{ content: string; language: Language } | null>(null)
  const startRecordingRef = useRef<() => void>(() => undefined)
  const initialSpeechStartedRef = useRef(false)
  const suppressRecognitionRestartRef = useRef(false)
  const speechGenerationRef = useRef(0)
  const busyRef = useRef(false)
  const overDetectorRef = useRef<{
    context: AudioContext
    source: MediaStreamAudioSourceNode
    processor: ScriptProcessorNode
    samples: number[]
    processing: boolean
  } | null>(null)

  const speak = useCallback((value: string, language: Language) => {
    const generation = ++speechGenerationRef.current
    if (handsFreeRef.current) {
      suppressRecognitionRestartRef.current = true
      recognitionRef.current?.stop()
    }
    speechSynthesis.cancel()
    const parts = value.match(/[^。！？.!?]+[。！？.!?]?/g)?.map(part => part.trim()).filter(Boolean) ?? [value]
    parts.forEach((part, index) => {
      const utterance = new SpeechSynthesisUtterance(part); utterance.lang = locale[language]; utterance.rate = 1.2; utterance.pitch = 1.0
      utterance.onstart = () => setSpeechState('speaking')
      utterance.onend = () => {
        if (generation === speechGenerationRef.current && index === parts.length - 1) {
          suppressRecognitionRestartRef.current = false
          window.setTimeout(() => {
            try { recognitionRef.current?.start() } catch { /* already running */ }
          }, 100)
          setSpeechState('ready')
          if (handsFreeRef.current) window.setTimeout(() => startRecordingRef.current(), 0)
        }
      }
      speechSynthesis.speak(utterance)
    })
  }, [])

  const load = useCallback(async () => {
    const data = await api<SessionPayload>(`/api/sessions/${sessionId}`); setPayload(data)
  }, [sessionId])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!payload || payload.session.status === 'ended') return
    let cancelled = false
    setWhisperReady(false)
    void preloadBrowserWhisper(setLiveTranscript)
      .then(() => {
        if (!cancelled) {
          setWhisperReady(true)
          setLiveTranscript('ブラウザWhisperの準備が完了しました')
        }
      })
      .catch(caught => {
        if (!cancelled) {
          const message = caught instanceof Error ? caught.message : 'ブラウザWhisperを利用できません'
          setLiveTranscript(`ブラウザWhisperを利用できません: ${message}`)
          setError(message)
        }
      })
    return () => { cancelled = true }
  }, [payload?.session.id, payload?.session.status])
  useEffect(() => {
    if (!payload || payload.session.status === 'ended' || handsFreeRef.current) return
    const timer = window.setTimeout(() => {
      if (!handsFreeRef.current && !busyRef.current) toggleHandsFree()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [payload?.session.id, payload?.session.status])
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
  useEffect(() => () => {
    const recognition = recognitionRef.current; recognitionRef.current = null; recognition?.stop()
    stopOverDetector()
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
    const detector = { context, source, processor, samples: [] as number[], processing: false }
    overDetectorRef.current = detector
    processor.onaudioprocess = event => {
      if (overDetectorRef.current !== detector) return
      detector.samples.push(...event.inputBuffer.getChannelData(0))
      const maxSamples = Math.round(context.sampleRate * 4)
      if (detector.samples.length > maxSamples) detector.samples.splice(0, detector.samples.length - maxSamples)
      if (detector.processing || detector.samples.length < context.sampleRate * 1.2) return
      detector.processing = true
      const snapshot = new Float32Array(detector.samples)
      void detectOverInBrowser(snapshot, context.sampleRate, language)
        .then(found => {
          if (found && recordingRef.current) {
            stopOverDetector()
            stopRecording()
          }
        })
        .catch(error => console.warn('[AudioInterview][Whisper] local over detection failed', error))
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
    setLiveTranscript('音声を解析しています…')
    const browserResult = await transcribeInBrowser(blob, payload.session.language, setLiveTranscript)
    const prepared = prepareLocalTranscript(browserResult.rawText)
    const result: { rawText: string; normalizedText?: string; maskedText?: string } = { rawText: browserResult.rawText, ...prepared }
    if (sequence === transcriptionSequenceRef.current) {
      setLiveTranscript(result.rawText)
    }
    return result
  }

  async function startRecording() {
    if (!payload || payload.session.status === 'ended' || recordingRef.current || busyRef.current || finalizingRef.current) return
    if (!whisperReady) {
      setError('Whisperモデルを読み込み中です。読み込み完了後に録音してください')
      return
    }
    try {
      setError(''); setLiveTranscript(''); finalizingRef.current = false
      commandTranscriptRef.current = ''
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true }); streamRef.current = stream
      const recorder = new MediaRecorder(stream); chunksRef.current = []; recorderRef.current = recorder
      recorder.ondataavailable = event => {
        if (!event.data.size) return
        chunksRef.current.push(event.data)
      }
      recorder.onstop = () => { void finishRecording(recorder.mimeType) }
      recorder.start(); recordingRef.current = true; setIsRecording(true); setSpeechState('recording'); beep(880)
      startOverDetector(stream, payload.session.language)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'マイクを開始できません'); setSpeechState('error') }
  }
  startRecordingRef.current = startRecording

  async function finishRecording(mimeType: string) {
    recordingRef.current = false; setIsRecording(false); finalizingRef.current = true
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
      const answer = (result?.maskedText ?? result?.rawText ?? '').trim().replace(/(?:\s|^)(?:over|オーバー|おーばー)\s*$/i, '').trim()
      if (answer) await send(answer, 'voice', result?.rawText, true, result?.maskedText)
      else {
        setError('音声を認識できませんでした。もう一度、少し長めに話してください')
        setSpeechState('ready')
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '音声認識に失敗しました'); setSpeechState('error')
    }
    finally { recorderRef.current = null; finalizingRef.current = false }
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
    // Keep recognition fully local: recording starts automatically and a
    // short rolling PCM window is checked by the local Whisper runtime.
    handsFreeRef.current = true; setHandsFree(true); setSpeechState('wake')
    if (!streamingMessageId && speechState === 'ready' && !recordingRef.current) {
      window.setTimeout(() => { void startRecording() }, 0)
    }
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
      const newUser = result.messages.find(message => message.role === 'user' && !beforeIds.has(message.id))
      if (newUser && displayText) setDisplayOverrides(current => ({ ...current, [newUser.id]: displayText }))
      setPayload(result); setText(''); setEditingId(null); onSessionsChanged()
      const assistant = [...result.messages].reverse().find(message => message.role === 'system')
      if (assistant) {
        setDisplayOverrides(current => ({ ...current, [assistant.id]: '' }))
        pendingSpeechRef.current = handsFreeRef.current && result.session.status !== 'ended'
          ? { content: assistant.content, language: result.session.language }
          : null
        setStreamingMessageId(assistant.id)
      } else setSpeechState(result.session.status === 'ended' ? 'ended' : 'ready')
    } catch (caught) { setError(caught instanceof Error ? caught.message : '送信できませんでした'); setSpeechState('error') }
    finally { if (manageBusy) { busyRef.current = false; setIsBusy(false) } }
  }

  async function sendText() {
    if (!text.trim() || busyRef.current) return
    await send(text, 'text')
  }

  async function endInterview() {
    if (!payload || !confirm('このインタビューを終了しますか？')) return
    const result = await api<SessionPayload>(`/api/sessions/${payload.session.id}/end`, { method: 'POST' }); setPayload(result); setSpeechState('ended'); onSessionsChanged(); window.setTimeout(onExit, 2400)
  }

  if (!payload) return <div className="loading">セッションを読み込んでいます…</div>
  const latestQuestion = [...payload.messages].reverse().find(message => message.role === 'system')
  const isThinking = speechState === 'thinking' && !streamingMessageId
  const interviewerIsActive = speechState === 'speaking' || isThinking || Boolean(streamingMessageId)
  const userIsActive = speechState === 'recording' || speechState === 'transcribing'
  return <section className={`interview-layout ${interviewerIsActive ? 'interviewer-active' : ''} ${userIsActive ? 'user-active' : ''}`}>
    <div className="interview-scene alpaca-background" style={{ backgroundImage: `url(${alpacaBackground})` }} aria-hidden="true"><div className="scene-shade" /></div>
    <header className="interview-header"><div className={`speech-status ${speechState}`}><i />{isThinking ? 'インタビュアーが考え中…' : labels[speechState]}</div><button className="danger-outline" onClick={endInterview} disabled={payload.session.status === 'ended'}>終了</button></header>
    <div className="interview-stage">
      <div className={`assistant-bubble ${isThinking ? 'thinking' : ''}`} aria-live="polite">
        <span>interviewer</span>
        {isThinking ? <div className="thinking-dots"><i /><i /><i /></div> : <p>{latestQuestion ? (displayOverrides[latestQuestion.id] || latestQuestion.content) : 'よろしくお願いします。'}</p>}
      </div>
    </div>
    {liveTranscript && <div className="live-strip"><span><b>Whisper</b>{liveTranscript}</span></div>}
    <footer className="composer">
      {editingId && <div className="editing-banner">過去の回答を編集中。この時点以降を再生成します。<button onClick={() => { setEditingId(null); setText('') }}>取消</button></div>}
      {error && <p className="error-message composer-error">{error}</p>}
      <textarea id="answer" value={isRecording || speechState === 'transcribing' ? liveTranscript : text} onChange={event => setText(event.target.value)} onFocus={() => { if (recordingRef.current) stopRecording() }} onKeyDown={event => {
        const nativeEvent = event.nativeEvent as KeyboardEvent
        if (event.key === 'Enter' && !event.shiftKey && !nativeEvent.isComposing && nativeEvent.keyCode !== 229) { event.preventDefault(); void sendText() }
      }} placeholder={payload.session.status === 'ended' ? 'このインタビューは終了しました' : '回答を入力（変換中はEnterで確定／確定後Enterで送信）'} disabled={payload.session.status === 'ended' || isBusy} />
      <div className="composer-actions minimal-actions">
        <button className={`handsfree-button ${handsFree ? 'active' : ''}`} onClick={toggleHandsFree} disabled={payload.session.status === 'ended' || isBusy}>{handsFree ? '自動録音中（停止）' : '自動録音を開始'}</button>
        <button className="primary send" onClick={() => void sendText()} disabled={!text.trim() || payload.session.status === 'ended' || isBusy}>{isBusy ? '送信中…' : '送信'}</button>
      </div>
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
  const initialSessionResolved = useRef(false)

  const loadSessions = useCallback(async () => {
    try {
      const result = await api<{ sessions: Session[] }>('/api/sessions')
      setSessions(result.sessions)
      if (!initialSessionResolved.current) {
        initialSessionResolved.current = true
        if (result.sessions[0]) setSelectedId(result.sessions[0].id)
      }
    } catch { /* login handles auth */ }
  }, [])
  useEffect(() => { api<{ account: Account }>('/api/me').then(result => { setAccount(result.account); setAuthChecked(true) }).catch(() => setAuthChecked(true)) }, [])
  useEffect(() => { if (account) void loadSessions() }, [account, loadSessions])
  useEffect(() => { if (account?.role === 'admin') setView('admin') }, [account])

  async function createSession() {
    // Ask for microphone access from the user's click, so the interview view can
    // enter hey-waiting immediately instead of prompting during the transition.
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      stream.getTracks().forEach(track => track.stop())
    } catch { /* Text input remains available when microphone access is denied. */ }
    const result = await api<SessionPayload>('/api/sessions', jsonInit('POST', { language })); await api(`/api/sessions/${result.session.id}/start`, { method: 'POST' }); setSelectedId(result.session.id); setView('interview'); await loadSessions()
  }
  async function signOut() { await api('/api/auth/logout', { method: 'POST' }); setAccount(null); setSessions([]); setSelectedId(null); initialSessionResolved.current = false }
  if (!authChecked) return <div className="loading">AudioInterviewを準備しています…</div>
  if (!account) return <Login onLogin={value => { setAccount(value); setView(value.role === 'admin' ? 'admin' : 'interview'); setAuthChecked(true) }} />

  const inInterview = view === 'interview' && Boolean(selectedId)
  return <div className={`app-shell ${inInterview ? 'interview-app' : ''}`}>
    <aside className="sidebar"><div className="sidebar-brand"><span>AI</span><strong>AudioInterview</strong></div>{account.role === 'admin' && <button className={`admin-entry ${view === 'admin' ? 'selected' : ''}`} onClick={() => setView('admin')}>⚙ ID発行・管理画面</button>}<button className="new-session" onClick={createSession}>＋ 新しいインタビュー</button><label className="language-picker">言語<select value={language} onChange={event => setLanguage(event.target.value as Language)}>{Object.entries(languageLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <nav><p>セッション</p>{sessions.map(item => <button key={item.id} className={selectedId === item.id && view === 'interview' ? 'selected' : ''} onClick={() => { setSelectedId(item.id); setView('interview') }}><span>{item.title}</span><small>{languageLabels[item.language]} · {item.status}</small></button>)}</nav>
      <div className="sidebar-bottom"><div className="account-chip"><span className="avatar small">{account.displayName.slice(0, 1)}</span><div><strong>{account.displayName}</strong><small>{account.id}</small></div><button title="ログアウト" onClick={signOut}>↪</button></div></div>
    </aside>
    <main className="workspace">{view === 'admin' ? <AdminPanel onOpenSession={id => { setSelectedId(id); setView('interview') }} /> : selectedId ? <Interview key={selectedId} sessionId={selectedId} onSessionsChanged={loadSessions} onExit={() => setSelectedId(null)} /> : <div className="empty-state"><div>✦</div><h2>インタビューを始めましょう</h2><p>言語を選び、「新しいインタビュー」を押してください。</p><button className="primary" onClick={createSession}>新しいインタビュー</button></div>}</main>
  </div>
}

export default App
