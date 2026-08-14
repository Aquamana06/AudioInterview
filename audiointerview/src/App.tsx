import { useCallback, useEffect, useRef, useState } from 'react'
import QRCode from 'qrcode'
import './App.css'

type Language = 'ja' | 'en' | 'de'
type Role = 'admin' | 'operator'
type Account = { id: string; role: Role; displayName: string }
type Session = { id: string; account_id: string; title: string; language: Language; status: 'running' | 'ended'; phase: 'profile' | 'interview'; profile_turn_count: number; started_at: string; updated_at: string }
type Message = { id: string; role: 'system' | 'user'; content: string; inputMode: 'text' | 'voice' | 'system'; createdAt: string; updatedAt: string }
type InterviewState = { task_coverage: number; task_depth: number; irregular_coverage: number; turn_count: number }
type WorkerProfile = { workerId: string; role: string | null; department: string | null; totalExperienceYears: number | null; currentRoleExperienceYears: number | null; assignedProcesses: string[]; assignedEquipment: string[]; responsibilities: string[]; qualifications: string[]; expertise: string[]; educationExperience: string[]; updatedAt: string | null }
type LongTermMemory = { id: string; type: string; content: string; sourceSessionId: string | null; createdAt: string }
type SessionSummary = { sessionId: string; summary: string; topics: string[]; unresolvedTopics: string[] }
type WorkerContext = { profile: WorkerProfile; memories: LongTermMemory[]; recentSessionSummaries: SessionSummary[] }
type SessionPayload = { session: Session; messages: Message[]; state: InterviewState; stateLabel: 'running' | 'end'; workerProfile: WorkerProfile; longTermMemories: LongTermMemory[]; sessionSummary: SessionSummary | null }
type SpeechState = 'ready' | 'wake' | 'recording' | 'transcribing' | 'thinking' | 'speaking' | 'ended' | 'error'

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
type BarcodeDetectorLike = { detect(source: ImageBitmap): Promise<Array<{ rawValue: string }>> }

const labels: Record<SpeechState, string> = {
  ready: 'Ready', wake: 'Listening for “hey whisper”', recording: 'Recording', transcribing: 'Local Whisper transcribing',
  thinking: 'Interviewer thinking', speaking: 'Speaking', ended: 'Ended', error: 'Error',
}
const languageLabels: Record<Language, string> = { ja: '日本語', en: 'English', de: 'Deutsch' }
const locale: Record<Language, string> = { ja: 'ja-JP', en: 'en-US', de: 'de-DE' }
const localBackendUrl = import.meta.env.VITE_LOCAL_INTERVIEW_BACKEND_URL ?? 'http://127.0.0.1:8000'

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
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

function ProfilePanel() {
  const [context, setContext] = useState<WorkerContext | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api<WorkerContext>('/api/profile').then(setContext).catch(caught => setError(caught instanceof Error ? caught.message : '読み込めませんでした')) }, [])
  if (error) return <div className="empty-state"><p className="error-message">{error}</p></div>
  if (!context) return <div className="loading">プロフィールと記憶を読み込んでいます…</div>
  const profile = context.profile
  const rows: Array<[string, string | number | null | string[]]> = [
    ['現在の役割', profile.role], ['部署', profile.department], ['総経験年数', profile.totalExperienceYears],
    ['現在業務の経験年数', profile.currentRoleExperienceYears], ['担当工程', profile.assignedProcesses],
    ['担当設備', profile.assignedEquipment], ['担当業務', profile.responsibilities], ['資格', profile.qualifications],
    ['得意領域', profile.expertise], ['教育経験', profile.educationExperience],
  ]
  return <div className="memory-page">
    <header><h1>プロフィールと継続記憶</h1><p>セッション進行状態とは分離され、作業員単位で引き継がれる情報です。</p></header>
    <section className="panel"><h2>Worker Profile</h2><dl className="profile-details">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{Array.isArray(value) ? value.join('、') || '未登録' : value ?? '未登録'}{typeof value === 'number' ? '年' : ''}</dd></div>)}</dl></section>
    <section className="panel"><h2>Long-term Memory</h2><div className="memory-list">{context.memories.length ? context.memories.map(item => <article key={item.id}><span>{item.type}</span><p>{item.content}</p></article>) : <p className="muted">継続記憶はまだありません。</p>}</div></section>
    <section className="panel"><h2>過去セッション要約</h2><div className="memory-list">{context.recentSessionSummaries.length ? context.recentSessionSummaries.map(item => <article key={item.sessionId}><p>{item.summary}</p>{item.unresolvedTopics.length > 0 && <small>未深掘り: {item.unresolvedTopics.join('、')}</small>}</article>) : <p className="muted">終了済みセッションはまだありません。</p>}</div></section>
  </div>
}

function Interview({ sessionId, account, onSessionsChanged }: { sessionId: string; account: Account; onSessionsChanged: () => void }) {
  const [payload, setPayload] = useState<SessionPayload | null>(null)
  const [text, setText] = useState('')
  const [displayOverrides, setDisplayOverrides] = useState<Record<string, string>>({})
  const [speechState, setSpeechState] = useState<SpeechState>('ready')
  const [liveTranscript, setLiveTranscript] = useState('')
  const [normalizedTranscript, setNormalizedTranscript] = useState('')
  const [maskedTermCount, setMaskedTermCount] = useState(0)
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [handsFree, setHandsFree] = useState(false)
  const [isRecording, setIsRecording] = useState(false)
  const [isBusy, setIsBusy] = useState(false)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const recordingRef = useRef(false)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const handsFreeRef = useRef(false)
  const previewBusyRef = useRef(false)
  const finalizingRef = useRef(false)
  const transcriptionSequenceRef = useRef(0)
  const endRef = useRef<HTMLDivElement | null>(null)

  const load = useCallback(async () => {
    const data = await api<SessionPayload>(`/api/sessions/${sessionId}`); setPayload(data)
  }, [sessionId])
  useEffect(() => { void load() }, [load])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [payload?.messages])
  useEffect(() => () => {
    const recognition = recognitionRef.current; recognitionRef.current = null; recognition?.stop()
    streamRef.current?.getTracks().forEach(track => track.stop())
  }, [])

  function beep(frequency: number, duration = 0.16) {
    const context = new AudioContext(); const oscillator = context.createOscillator(); const gain = context.createGain()
    oscillator.frequency.value = frequency; oscillator.connect(gain); gain.connect(context.destination); oscillator.start()
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + duration); oscillator.stop(context.currentTime + duration)
  }

  async function transcribe(blob: Blob, mode: 'preview' | 'final') {
    if (!blob.size || !payload) return null
    const sequence = ++transcriptionSequenceRef.current
    const form = new FormData(); form.append('audio', blob, 'interview.webm'); form.append('language', payload.session.language)
    const result = await api<{ rawText: string; normalizedText: string; maskedText: string }>(`${localBackendUrl}/transcribe`, { method: 'POST', body: form })
    if (mode === 'preview' && !finalizingRef.current && sequence === transcriptionSequenceRef.current) setLiveTranscript(result.rawText)
    if (mode === 'final' && sequence === transcriptionSequenceRef.current) {
      setLiveTranscript(result.rawText)
      setNormalizedTranscript(result.normalizedText)
      setMaskedTermCount((result.maskedText.match(/<[A-Z_]+_[A-Z]+>/g) ?? []).length)
    }
    return result
  }

  async function startRecording() {
    if (!payload || payload.session.status === 'ended' || recordingRef.current || isBusy) return
    try {
      setError(''); setLiveTranscript(''); setNormalizedTranscript(''); setMaskedTermCount(0); finalizingRef.current = false
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true }); streamRef.current = stream
      const recorder = new MediaRecorder(stream); chunksRef.current = []; recorderRef.current = recorder
      recorder.ondataavailable = event => {
        if (!event.data.size) return
        chunksRef.current.push(event.data)
        if (recorder.state === 'recording' && !previewBusyRef.current && !finalizingRef.current) {
          previewBusyRef.current = true
          void transcribe(new Blob([...chunksRef.current], { type: recorder.mimeType || 'audio/webm' }), 'preview').catch(() => undefined).finally(() => { previewBusyRef.current = false })
        }
      }
      recorder.onstop = () => { void finishRecording(recorder.mimeType) }
      recorder.start(3000); recordingRef.current = true; setIsRecording(true); setSpeechState('recording'); beep(880)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'マイクを開始できません'); setSpeechState('error') }
  }

  async function finishRecording(mimeType: string) {
    recordingRef.current = false; setIsRecording(false); finalizingRef.current = true
    streamRef.current?.getTracks().forEach(track => track.stop()); streamRef.current = null; setSpeechState('transcribing'); beep(520, 0.3)
    try {
      const blob = new Blob(chunksRef.current, { type: mimeType || 'audio/webm' })
      const result = await transcribe(blob, 'final')
      if (result?.maskedText.trim()) await send(result.maskedText, 'voice', result.normalizedText)
      else setSpeechState('ready')
    } catch (caught) { setError(caught instanceof Error ? caught.message : '音声認識に失敗しました'); setSpeechState('error') }
    finally { recorderRef.current = null; finalizingRef.current = false }
  }

  function stopRecording() {
    if (recorderRef.current?.state === 'recording') { recordingRef.current = false; setIsRecording(false); recorderRef.current.stop() }
  }

  function toggleHandsFree() {
    if (handsFree) {
      const recognition = recognitionRef.current; recognitionRef.current = null; recognition?.stop()
      handsFreeRef.current = false; setHandsFree(false); if (!recordingRef.current) setSpeechState('ready'); return
    }
    const win = window as typeof window & { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike }
    const Constructor = win.SpeechRecognition || win.webkitSpeechRecognition
    if (!Constructor) { setError('このブラウザは起動語検知に対応していません。録音ボタンは利用できます。'); return }
    const recognition = new Constructor(); recognition.continuous = true; recognition.interimResults = true; recognition.lang = locale[payload?.session.language ?? 'ja']
    recognition.onresult = event => {
      let heard = ''; for (let i = event.resultIndex; i < event.results.length; i += 1) heard += event.results[i][0].transcript
      const lowered = heard.toLowerCase().replace(/[,.!?。、！？]/g, '').trim(); setLiveTranscript(heard)
      if (/hey\s*(whisper|ウィスパー|ウイスパー)/i.test(lowered) && !recordingRef.current) void startRecording()
      if (/(^|\s)(over|オーバー)(\s|$)/i.test(lowered) && recordingRef.current) stopRecording()
    }
    recognition.onend = () => { if (recognitionRef.current === recognition) { try { recognition.start() } catch { /* browser restart race */ } } }
    recognition.onerror = () => setError('起動語の聞き取りを再試行しています')
    recognitionRef.current = recognition; recognition.start(); handsFreeRef.current = true; setHandsFree(true); setSpeechState('wake')
  }

  async function send(maskedText: string, inputMode: 'text' | 'voice', displayText?: string, manageBusy = true) {
    if (!payload || !maskedText.trim()) return
    if (manageBusy) setIsBusy(true)
    setSpeechState('thinking'); setError('')
    try {
      const beforeIds = new Set(payload.messages.map(message => message.id))
      const result = await api<SessionPayload>(`/api/sessions/${payload.session.id}/messages`, jsonInit('POST', { maskedText, inputMode, editMessageId: editingId || undefined }))
      const newUser = result.messages.find(message => message.role === 'user' && !beforeIds.has(message.id))
      if (newUser && displayText) setDisplayOverrides(current => ({ ...current, [newUser.id]: displayText }))
      setPayload(result); setText(''); setEditingId(null); onSessionsChanged()
      const assistant = [...result.messages].reverse().find(message => message.role === 'system')
      if (inputMode === 'voice' && assistant && result.session.status !== 'ended') speak(assistant.content, result.session.language)
      else setSpeechState(result.session.status === 'ended' ? 'ended' : handsFree ? 'wake' : 'ready')
    } catch (caught) { setError(caught instanceof Error ? caught.message : '送信できませんでした'); setSpeechState('error') }
    finally { if (manageBusy) setIsBusy(false) }
  }

  async function sendText() {
    if (!text.trim() || isBusy) return
    setIsBusy(true); setSpeechState('transcribing'); setError('')
    try {
      const masked = await api<{ normalizedText: string; maskedText: string }>(`${localBackendUrl}/mask-text`, jsonInit('POST', { text }))
      await send(masked.maskedText, 'text', masked.normalizedText, false)
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'ローカル秘匿処理に失敗しました'); setSpeechState('error') }
    finally { setIsBusy(false) }
  }

  function speak(value: string, language: Language) {
    speechSynthesis.cancel(); const utterance = new SpeechSynthesisUtterance(value); utterance.lang = locale[language]
    utterance.onstart = () => setSpeechState('speaking')
    utterance.onend = () => {
      if (handsFreeRef.current) void startRecording()
      else setSpeechState('ready')
    }
    speechSynthesis.speak(utterance)
  }

  async function endInterview() {
    if (!payload || !confirm('このインタビューを終了しますか？')) return
    const result = await api<SessionPayload>(`/api/sessions/${payload.session.id}/end`, { method: 'POST' }); setPayload(result); setSpeechState('ended'); onSessionsChanged()
  }

  if (!payload) return <div className="loading">セッションを読み込んでいます…</div>
  return <section className="interview-layout">
    <header className="interview-header"><div><h2>{payload.session.title}</h2><span>{languageLabels[payload.session.language]} · {account.displayName}</span></div><div className={`speech-status ${speechState}`}><i />{labels[speechState]}</div><button className="danger-outline" onClick={endInterview} disabled={payload.session.status === 'ended'}>インタビュー終了</button></header>
    <div className="messages" aria-live="polite">
      {payload.messages.map(message => <article key={message.id} className={`message ${message.role}`}>
        <div className="avatar">{message.role === 'system' ? 'AI' : account.displayName.slice(0, 1)}</div>
        <div className="bubble"><div className="message-meta"><strong>{message.role === 'system' ? 'インタビュアー' : account.displayName}</strong><span>{message.inputMode === 'voice' ? '🎙 音声' : ''}</span></div><p>{displayOverrides[message.id] || message.content}</p>
          {message.role === 'user' && payload.session.status !== 'ended' && <button className="edit-link" onClick={() => { setEditingId(message.id); setText(displayOverrides[message.id] || message.content); document.querySelector<HTMLTextAreaElement>('#answer')?.focus() }}>編集してここから再生成</button>}
        </div>
      </article>)}<div ref={endRef} />
    </div>
    {(liveTranscript || normalizedTranscript) && <div className="live-strip"><span><b>Whisper</b>{liveTranscript}</span><span><b>専門用語補正</b>{normalizedTranscript}</span><span className={maskedTermCount ? 'mask-applied' : ''}><b>Semantic Masking</b>{maskedTermCount ? `${maskedTermCount}件適用済み` : '対象語なし'}</span></div>}
    <footer className="composer">
      {editingId && <div className="editing-banner">過去の回答を編集中。この時点以降を再生成します。<button onClick={() => { setEditingId(null); setText('') }}>取消</button></div>}
      {error && <p className="error-message composer-error">{error}</p>}
      <textarea id="answer" value={text} onChange={event => setText(event.target.value)} onFocus={() => { if (recordingRef.current) stopRecording() }} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendText() } }} placeholder={payload.session.status === 'ended' ? 'このインタビューは終了しました' : '回答を入力（Enterで送信、Shift+Enterで改行）'} disabled={payload.session.status === 'ended' || isBusy} />
      <div className="composer-actions"><button className={handsFree ? 'active-voice' : ''} onClick={toggleHandsFree} disabled={payload.session.status === 'ended' || isBusy}>⌁ {handsFree ? '起動語の待受を停止' : 'ハンズフリー待受を開始'}</button><button onClick={isRecording ? stopRecording : startRecording} disabled={payload.session.status === 'ended' || isBusy}>{isRecording ? '■ 録音して送信' : '● 今すぐ録音'}</button><button className="primary send" onClick={() => void sendText()} disabled={!text.trim() || payload.session.status === 'ended' || isBusy}>{isBusy ? '処理中…' : 'テキスト送信'}</button></div>
      <p className="voice-help">ハンズフリー：最初は「hey whisper」で録音開始。以後はAIの読み上げ終了後に自動録音し、「over」で停止・送信します。 今すぐ録音：起動語なしで開始します。</p>
      <p className="privacy-note">音声はローカルWhisperで処理され、専門用語補正・Semantic Masking後のテキストだけをAIへ送信します。</p>
    </footer>
  </section>
}

function App() {
  const [account, setAccount] = useState<Account | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [view, setView] = useState<'interview' | 'profile' | 'admin'>('interview')
  const [language, setLanguage] = useState<Language>('ja')
  const [authChecked, setAuthChecked] = useState(false)

  const loadSessions = useCallback(async () => {
    try { const result = await api<{ sessions: Session[] }>('/api/sessions'); setSessions(result.sessions); if (!selectedId && result.sessions[0]) setSelectedId(result.sessions[0].id) } catch { /* login handles auth */ }
  }, [selectedId])
  useEffect(() => { api<{ account: Account }>('/api/me').then(result => { setAccount(result.account); setAuthChecked(true) }).catch(() => setAuthChecked(true)) }, [])
  useEffect(() => { if (account) void loadSessions() }, [account, loadSessions])
  useEffect(() => { if (account?.role === 'admin') setView('admin') }, [account])

  async function createSession() {
    const result = await api<SessionPayload>('/api/sessions', jsonInit('POST', { language })); await api(`/api/sessions/${result.session.id}/start`, { method: 'POST' }); setSelectedId(result.session.id); setView('interview'); await loadSessions()
  }
  async function signOut() { await api('/api/auth/logout', { method: 'POST' }); setAccount(null); setSessions([]); setSelectedId(null) }
  if (!authChecked) return <div className="loading">AudioInterviewを準備しています…</div>
  if (!account) return <Login onLogin={value => { setAccount(value); setView(value.role === 'admin' ? 'admin' : 'interview'); setAuthChecked(true) }} />

  return <div className="app-shell">
    <aside className="sidebar"><div className="sidebar-brand"><span>AI</span><strong>AudioInterview</strong></div>{account.role === 'admin' && <button className={`admin-entry ${view === 'admin' ? 'selected' : ''}`} onClick={() => setView('admin')}>⚙ ID発行・管理画面</button>}<button className={`profile-entry ${view === 'profile' ? 'selected' : ''}`} onClick={() => setView('profile')}>◎ プロフィール・継続記憶</button><button className="new-session" onClick={createSession}>＋ 新しいインタビュー</button><label className="language-picker">言語<select value={language} onChange={event => setLanguage(event.target.value as Language)}>{Object.entries(languageLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <nav><p>セッション</p>{sessions.map(item => <button key={item.id} className={selectedId === item.id && view === 'interview' ? 'selected' : ''} onClick={() => { setSelectedId(item.id); setView('interview') }}><span>{item.title}</span><small>{languageLabels[item.language]} · {item.status}</small></button>)}</nav>
      <div className="sidebar-bottom"><div className="account-chip"><span className="avatar small">{account.displayName.slice(0, 1)}</span><div><strong>{account.displayName}</strong><small>{account.id}</small></div><button title="ログアウト" onClick={signOut}>↪</button></div></div>
    </aside>
    <main className="workspace">{view === 'admin' ? <AdminPanel onOpenSession={id => { setSelectedId(id); setView('interview') }} /> : view === 'profile' ? <ProfilePanel /> : selectedId ? <Interview key={selectedId} sessionId={selectedId} account={account} onSessionsChanged={loadSessions} /> : <div className="empty-state"><div>✦</div><h2>インタビューを始めましょう</h2><p>言語を選び、「新しいインタビュー」を押してください。</p><button className="primary" onClick={createSession}>新しいインタビュー</button></div>}</main>
  </div>
}

export default App
