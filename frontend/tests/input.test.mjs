import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'

test('text and voice input in the interview screen', async t => {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost/' })
  const globals = ['window', 'document', 'navigator', 'HTMLElement', 'IS_REACT_ACT_ENVIRONMENT',
    'speechSynthesis', 'SpeechSynthesisUtterance', 'AudioContext', 'MediaRecorder', 'fetch', 'confirm']
  const descriptors = new Map(globals.map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const install = (name, value) => Object.defineProperty(globalThis, name, { configurable: true, writable: true, value })
  install('window', dom.window)
  install('document', dom.window.document)
  install('navigator', dom.window.navigator)
  install('HTMLElement', dom.window.HTMLElement)
  install('IS_REACT_ACT_ENVIRONMENT', true)
  install('confirm', () => true)
  install('speechSynthesis', {
    cancel() {},
    speak(utterance) { queueMicrotask(() => { utterance.onstart?.(); utterance.onend?.() }) },
  })
  install('SpeechSynthesisUtterance', class { constructor(text) { this.text = text } })
  const audioNode = () => ({ connect() {}, disconnect() {}, gain: { value: 0, exponentialRampToValueAtTime() {} } })
  const processors = []
  install('AudioContext', class {
    sampleRate = 48000
    currentTime = 0
    destination = {}
    createMediaStreamSource() { return audioNode() }
    createScriptProcessor() { const node = audioNode(); processors.push(node); return node }
    createGain() { return audioNode() }
    createOscillator() { return { ...audioNode(), frequency: {}, start() {}, stop() {} } }
    async resume() {}
    async close() {}
  })
  const recorders = []
  install('MediaRecorder', class {
    state = 'inactive'
    mimeType = 'audio/webm'
    constructor() { recorders.push(this) }
    start() { this.state = 'recording' }
    stop() {
      this.state = 'inactive'
      this.ondataavailable?.({ data: new Blob(['audio'], { type: this.mimeType }) })
      this.onstop?.()
    }
  })
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    server: { middlewareMode: true, hmr: false, ws: false, watch: null },
  })
  t.after(async () => {
    await server.close()
    dom.window.close()
    for (const [key, descriptor] of descriptors) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else delete globalThis[key]
    }
  })
  const { default: App } = await server.ssrLoadModule('/src/App.tsx')
  const { act, createElement } = await import('react')
  const { createRoot } = await import('react-dom/client')
  const pause = async (ms = 10) => act(async () => { await new Promise(resolve => setTimeout(resolve, ms)) })
  async function waitFor(condition, attempts = 100) {
    for (let i = 0; i < attempts; i++) {
      await pause()
      if (condition()) return
    }
    assert.fail('UI did not reach the expected state')
  }
  const click = async element => act(async () => { element.click() })
  async function setup(options = {}) {
    const calls = []
    let micCalls = 0
    let stoppedTracks = 0
    let microphone = async () => ({ getTracks: () => [{ stop() { stoppedTracks++ } }] })
    let speechResponse = async () => Response.json({ rawText: '音声回答', maskedText: '音声回答' })
    const spoken = []
    speechSynthesis.speak = utterance => {
      spoken.push(utterance)
      if (!options.manualSpeech) queueMicrotask(() => { utterance.onstart?.(); utterance.onend?.() })
    }
    let nextReplyEnds = false
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      getUserMedia() { micCalls++; return microphone() },
    } })
    const payload = {
      session: { id: 'test', account_id: 'operator', language: 'ja', status: options.status ?? 'running', title: 'test' },
      messages: [{ id: 'opening', role: 'system', content: options.status === 'ended' ? 'ありがとうございました。' : '？' }],
      state: { turn_count: 0 }, stateLabel: options.status === 'ended' ? 'end' : 'running',
      memory: { status: options.memoryStatus ?? (options.status === 'ended' ? 'ready' : 'not_started'), summary: null },
    }
    let createResponse = async () => Response.json(payload)
    let startResponse = async () => Response.json(payload)
    let detailResponse = async () => Response.json(payload)
    install('fetch', async (path, options = {}) => {
      calls.push({ path, options })
      if (path === '/api/me') return Response.json({ account: { id: 'operator', role: 'operator', displayName: 'テスト' } })
      if (path === '/api/sessions' && options.method !== 'POST') return Response.json({ sessions: initialSessions.map(item =>
        item.id === payload.session.id ? { ...item, ...payload.session, memory_status: payload.memory.status } : item) })
      if (path === '/api/sessions' && options.method === 'POST') {
        const response = await createResponse()
        if (response.ok && !initialSessions.some(item => item.id === payload.session.id)) initialSessions.push(payload.session)
        return response
      }
      if (path.endsWith('/start')) return startResponse()
      if (path === '/api/local/mask-text') return Response.json({ maskedText: JSON.parse(options.body).text })
      if (path === '/api/speech/transcribe') return speechResponse()
      if (path.endsWith('/messages')) {
        const body = JSON.parse(options.body)
        payload.messages.push({ id: 'answer', role: 'user', content: body.maskedText },
          { id: 'reply', role: 'system', content: nextReplyEnds ? 'ありがとうございました。これでインタビューを終了します。' : '？' })
        if (nextReplyEnds) {
          payload.session.status = 'ended'; payload.stateLabel = 'end'
          payload.memory = { status: 'pending', summary: null }
        }
      }
      if (path.endsWith('/end')) {
        payload.session.status = 'ended'; payload.stateLabel = 'end'
        payload.memory.status = 'pending'
        payload.messages.push({ id: 'ending', role: 'system', content: 'ありがとうございました。' })
      }
      if (path === '/api/sessions/test' && loadError) return Response.json({ error: '記録を読み込めませんでした' }, { status: 503 })
      if (path === '/api/sessions/test') return detailResponse()
      return Response.json(payload)
    })
    const initialSessions = options.sessions ?? []
    const loadError = options.loadError
    recorders.length = 0
    processors.length = 0
    const root = createRoot(document.getElementById('root'))
    await act(async () => { root.render(createElement(App)) })
    await waitFor(() => document.querySelector('.new-session'))
    if (options.openNewSession !== false) {
      await waitFor(() => !document.querySelector('.new-session').disabled)
      await click(document.querySelector('.new-session'))
      await waitFor(() => loadError ? document.querySelector('[role="alert"]') : document.querySelector('textarea'))
    }
    await pause(150)
    return {
      calls,
      get micCalls() { return micCalls },
      get stoppedTracks() { return stoppedTracks },
      get spoken() { return spoken },
      setMicrophone(fn) { microphone = fn },
      setSpeechResponse(fn) { speechResponse = fn },
      setCreateResponse(fn) { createResponse = fn },
      setStartResponse(fn) { startResponse = fn },
      setDetailResponse(fn) { detailResponse = fn },
      finishSaving(status = 'ready') { payload.memory.status = status },
      endOnNextReply() { nextReplyEnds = true },
      async dispose() { await act(async () => root.unmount()) },
      async type(text) {
        const textarea = document.querySelector('textarea')
        await act(async () => {
          textarea.focus()
          Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, 'value').set.call(textarea, text)
          textarea.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
        })
      },
    }
  }

  await t.test('text submission needs no microphone and preserves the answer', async () => {
    const ui = await setup()
    try {
      assert.equal(ui.micCalls, 0)
      await ui.type('設備を点検しました')
      assert.equal(document.querySelector('textarea').value, '設備を点検しました')
      await click(document.querySelector('.send'))
      await waitFor(() => ui.calls.some(call => call.path.endsWith('/messages')))
      const body = JSON.parse(ui.calls.find(call => call.path.endsWith('/messages')).options.body)
      assert.equal(body.maskedText, '設備を点検しました')
      assert.equal(body.inputMode, 'text')
      assert.equal(ui.micCalls, 0)
    } finally { await ui.dispose() }
  })

  await t.test('focusing text cancels recording without submitting audio', async () => {
    const ui = await setup()
    try {
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => recorders[0]?.state === 'recording')
      await ui.type('文字で回答します')
      assert.equal(recorders[0].state, 'inactive')
      assert.equal(ui.stoppedTracks, 1)
      assert.equal(document.querySelector('textarea').value, '文字で回答します')
      assert.equal(ui.calls.filter(call => call.path === '/api/speech/transcribe').length, 0)
    } finally { await ui.dispose() }
  })

  await t.test('stopping a voice answer submits the transcription as voice input', async () => {
    const ui = await setup()
    try {
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => recorders[0]?.state === 'recording')
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => ui.calls.some(call => call.path.endsWith('/messages')))
      const body = JSON.parse(ui.calls.find(call => call.path.endsWith('/messages')).options.body)
      assert.equal(body.inputMode, 'voice')
      assert.equal(body.maskedText, '音声回答')
    } finally { await ui.dispose() }
  })

  await t.test('voice feedback displays the corrected transcript used for the answer', async () => {
    const ui = await setup()
    try {
      ui.setSpeechResponse(async () => Response.json({
        rawText: '15等の温度は15度です。オーバー。',
        normalizedText: '重合塔の温度は15度です。',
        maskedText: '重合塔の温度は15度です。', endOfTurn: true,
      }))
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => recorders[0]?.state === 'recording')
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => ui.calls.some(call => call.path.endsWith('/messages')))
      assert.match(document.querySelector('.live-strip').textContent, /重合塔の温度は15度です。/)
      assert.doesNotMatch(document.querySelector('.live-strip').textContent, /15等|オーバー/)
      const body = JSON.parse(ui.calls.find(call => call.path.endsWith('/messages')).options.body)
      assert.equal(body.maskedText, '重合塔の温度は15度です。')
    } finally { await ui.dispose() }
  })

  await t.test('rolling recognition checks again after one second and automatically submits on a turn command', async t => {
    const ui = await setup()
    let now = 10000
    t.mock.method(Date, 'now', () => now)
    try {
      let recognitionCalls = 0
      ui.setSpeechResponse(async () => {
        recognitionCalls++
        return Response.json({ rawText: '確認しました。おば、', normalizedText: '確認しました。', maskedText: '確認しました。', endOfTurn: recognitionCalls > 1 })
      })
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => recorders[0]?.state === 'recording')
      const processor = processors[0]
      const samples = new Float32Array(48000 * 1.2)
      await act(async () => { processor.onaudioprocess({ inputBuffer: { getChannelData: () => samples } }) })
      assert.equal(recognitionCalls, 1)
      assert.equal(recorders[0].state, 'recording')
      now += 1100
      await act(async () => { processor.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array(4096) } }) })
      await waitFor(() => ui.calls.some(call => call.path.endsWith('/messages')))
      assert.equal(recorders[0].state, 'inactive')
      assert.equal(recognitionCalls, 3) // Two rolling windows and the full answer.
      assert.equal(ui.calls.filter(call => call.path.endsWith('/messages')).length, 1)
      assert.equal(JSON.parse(ui.calls.find(call => call.path.endsWith('/messages')).options.body).maskedText, '確認しました。')
    } finally { await ui.dispose() }
  })

  await t.test('hands-free recording resumes after a short spoken reply on successive turns', async () => {
    const ui = await setup()
    try {
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => recorders[0]?.state === 'recording')
      for (let turn = 0; turn < 2; turn++) {
        await act(async () => { recorders[turn].stop() })
        await waitFor(() => recorders[turn + 1]?.state === 'recording')
        assert.equal(ui.calls.filter(call => call.path.endsWith('/messages')).length, turn + 1)
      }
    } finally { await ui.dispose() }
  })

  await t.test('hands-free recording recovers after an empty transcription', async () => {
    const ui = await setup()
    try {
      ui.setSpeechResponse(async () => Response.json({ rawText: '', maskedText: '' }))
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => recorders[0]?.state === 'recording')
      await act(async () => { recorders[0].stop() })
      await waitFor(() => recorders[1]?.state === 'recording')
      assert.equal(ui.calls.filter(call => call.path.endsWith('/messages')).length, 0)
    } finally { await ui.dispose() }
  })

  await t.test('enabling voice waits for playback and resumes even if playback fails', async () => {
    const ui = await setup({ manualSpeech: true })
    try {
      const opening = ui.spoken[0]
      assert.ok(opening)
      await act(async () => { opening.onstart() })
      await click(document.querySelector('.handsfree-button'))
      await pause()
      assert.equal(ui.micCalls, 0)
      await act(async () => { opening.onerror({ error: 'synthesis-failed' }) })
      await waitFor(() => recorders[0]?.state === 'recording')
      // A callback from cancelled playback must not reset the recorder state.
      await act(async () => { opening.onstart(); opening.onend() })
      assert.equal(document.querySelector('.speech-status').textContent, 'Recording')
      assert.equal(ui.micCalls, 1)
    } finally { await ui.dispose() }
  })

  await t.test('automatic completion waits for recording to finish before returning home', async () => {
    const ui = await setup()
    try {
      ui.endOnNextReply()
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => recorders[0]?.state === 'recording')
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => document.querySelector('.saving-screen'))
      assert.match(document.querySelector('.saving-screen').textContent, /インタビューの内容を記録しています/)
      assert.equal(document.querySelector('.new-session').disabled, true)
      assert.equal(recorders[0].state, 'inactive')
      assert.ok(ui.stoppedTracks >= 1)
      assert.equal(ui.calls.filter(call => call.path.endsWith('/end')).length, 0)
      await pause(2500) // Completion must depend on the job, not the former 2.4s timer.
      assert.ok(document.querySelector('.saving-screen'))
      const createCount = ui.calls.filter(call => call.path === '/api/sessions' && call.options.method === 'POST').length
      await click(document.querySelector('.new-session'))
      assert.equal(ui.calls.filter(call => call.path === '/api/sessions' && call.options.method === 'POST').length, createCount)
      ui.finishSaving()
      await waitFor(() => document.querySelector('.empty-state'), 200)
      assert.equal(document.querySelector('.interview-layout'), null)
      assert.equal(document.querySelector('.new-session').disabled, false)
    } finally { await ui.dispose() }
  })

  await t.test('manual completion returns home after a fallback record is saved', async () => {
    const ui = await setup()
    try {
      await click(document.querySelector('.interview-header button'))
      await waitFor(() => document.querySelector('.saving-screen'))
      assert.equal(document.querySelector('.new-session').disabled, true)
      assert.equal(ui.calls.filter(call => call.path.endsWith('/end')).length, 1)
      ui.finishSaving('fallback')
      await waitFor(() => document.querySelector('.empty-state'), 200)
    } finally { await ui.dispose() }
  })

  await t.test('reload resumes waiting for a pending record', async () => {
    const ended = { id: 'test', account_id: 'operator', language: 'ja', status: 'ended', title: '記録中', memory_status: 'pending' }
    const ui = await setup({ status: 'ended', memoryStatus: 'pending', sessions: [ended], openNewSession: false })
    try {
      assert.ok(document.querySelector('.saving-screen'))
      assert.equal(document.querySelector('.new-session').disabled, true)
      ui.finishSaving()
      await waitFor(() => document.querySelector('.empty-state'), 200)
      assert.equal(document.querySelector('.new-session').disabled, false)
    } finally { await ui.dispose() }
  })

  await t.test('a transient recording status error keeps creation disabled and retries', async () => {
    const ui = await setup()
    try {
      ui.setDetailResponse(async () => Response.json({ error: '一時的なエラー' }, { status: 503 }))
      await click(document.querySelector('.interview-header button'))
      await waitFor(() => document.querySelector('.saving-screen .error-message'))
      assert.equal(document.querySelector('.new-session').disabled, true)
      ui.setDetailResponse(async () => Response.json({ memory: { status: 'ready' } }))
      ui.finishSaving()
      await waitFor(() => document.querySelector('.empty-state'), 200)
    } finally { await ui.dispose() }
  })

  await t.test('repeated start clicks send one create request and one start request', async () => {
    const ui = await setup({ openNewSession: false })
    try {
      let resolveCreate
      let resolveStart
      ui.setCreateResponse(() => new Promise(resolve => { resolveCreate = resolve }))
      ui.setStartResponse(() => new Promise(resolve => { resolveStart = resolve }))
      const sidebarButton = document.querySelector('.new-session')
      const homeButton = document.querySelector('.empty-state button')
      await act(async () => { sidebarButton.click(); homeButton.click(); sidebarButton.click() })
      assert.equal(ui.calls.filter(call => call.path === '/api/sessions' && call.options.method === 'POST').length, 1)
      assert.equal(sidebarButton.disabled, true)
      assert.match(document.querySelector('.workspace [role="status"]').textContent, /準備しています/)
      await act(async () => { resolveCreate(Response.json({ session: { id: 'test' } })) })
      await waitFor(() => Boolean(resolveStart))
      await click(sidebarButton)
      assert.equal(ui.calls.filter(call => call.path.endsWith('/start')).length, 1)
      await act(async () => { resolveStart(Response.json({})) })
      await waitFor(() => document.querySelector('textarea'))
      assert.equal(ui.calls.filter(call => call.path === '/api/sessions' && call.options.method === 'POST').length, 1)
    } finally { await ui.dispose() }
  })

  await t.test('retrying a failed opening reuses the created session', async () => {
    const ui = await setup({ openNewSession: false })
    try {
      ui.setStartResponse(async () => Response.json({ error: '開始できませんでした' }, { status: 503 }))
      await click(document.querySelector('.new-session'))
      await waitFor(() => document.querySelector('[role="alert"]'))
      assert.match(document.querySelector('[role="alert"]').textContent, /開始できませんでした/)
      assert.equal(document.querySelector('.new-session').disabled, false)
      ui.setStartResponse(async () => Response.json({}))
      await click(document.querySelector('.new-session'))
      await waitFor(() => document.querySelector('textarea'))
      assert.equal(ui.calls.filter(call => call.path === '/api/sessions' && call.options.method === 'POST').length, 1)
      assert.equal(ui.calls.filter(call => call.path.endsWith('/start')).length, 2)
    } finally { await ui.dispose() }
  })

  await t.test('reload does not automatically reopen an ended session and history can be exited', async () => {
    const ended = { id: 'test', language: 'ja', status: 'ended', title: '終了済み' }
    const ui = await setup({ status: 'ended', sessions: [ended], openNewSession: false })
    try {
      await waitFor(() => document.querySelector('.empty-state'))
      assert.equal(document.querySelector('.interview-layout'), null)
      assert.equal(ui.calls.filter(call => call.path === '/api/sessions/test').length, 0)
      await click(document.querySelector('.sidebar nav button'))
      await waitFor(() => document.querySelector('.interview-header button'))
      assert.equal(document.querySelector('.interview-header button').textContent, 'ホームに戻る')
      assert.equal(document.querySelector('.speech-status').textContent, 'Ended')
      await click(document.querySelector('.interview-header button'))
      await waitFor(() => document.querySelector('.empty-state'))
    } finally { await ui.dispose() }
  })

  await t.test('session loading failure offers retry and a way home', async () => {
    const ui = await setup({ loadError: true })
    try {
      assert.match(document.querySelector('[role="alert"]').textContent, /記録を読み込めませんでした/)
      assert.ok([...document.querySelectorAll('.loading button')].some(button => button.textContent === '再試行'))
      await click([...document.querySelectorAll('.loading button')].find(button => button.textContent === 'ホームに戻る'))
      await waitFor(() => document.querySelector('.empty-state'))
    } finally { await ui.dispose() }
  })

  await t.test('late microphone permission cannot start recording after switching to text', async () => {
    const ui = await setup()
    try {
      let resolve
      ui.setMicrophone(() => new Promise(done => { resolve = done }))
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => ui.micCalls === 1)
      await ui.type('先にテキスト入力')
      let stopped = false
      await act(async () => { resolve({ getTracks: () => [{ stop() { stopped = true } }] }) })
      assert.equal(stopped, true)
      assert.equal(recorders.length, 0)
    } finally { await ui.dispose() }
  })

  await t.test('a late transcription cannot submit over a text answer', async () => {
    const ui = await setup()
    try {
      let resolve
      ui.setSpeechResponse(() => new Promise(done => { resolve = done }))
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => recorders[0]?.state === 'recording')
      await click(document.querySelector('.handsfree-button'))
      await waitFor(() => Boolean(resolve))
      await ui.type('こちらを送ります')
      await click(document.querySelector('.send'))
      await waitFor(() => ui.calls.some(call => call.path.endsWith('/messages')))
      await act(async () => { resolve(Response.json({ rawText: '古い音声', maskedText: '古い音声' })) })
      const messages = ui.calls.filter(call => call.path.endsWith('/messages'))
      assert.equal(messages.length, 1)
      assert.equal(JSON.parse(messages[0].options.body).inputMode, 'text')
    } finally { await ui.dispose() }
  })
})
