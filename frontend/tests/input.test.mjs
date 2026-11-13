import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { JSDOM } from 'jsdom'
import { createServer } from 'vite'

test('text and voice input in the interview screen', async t => {
  const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost/' })
  const globals = ['window', 'document', 'navigator', 'HTMLElement', 'IS_REACT_ACT_ENVIRONMENT',
    'speechSynthesis', 'SpeechSynthesisUtterance', 'AudioContext', 'MediaRecorder', 'fetch']
  const descriptors = new Map(globals.map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const install = (name, value) => Object.defineProperty(globalThis, name, { configurable: true, writable: true, value })
  install('window', dom.window)
  install('document', dom.window.document)
  install('navigator', dom.window.navigator)
  install('HTMLElement', dom.window.HTMLElement)
  install('IS_REACT_ACT_ENVIRONMENT', true)
  install('speechSynthesis', {
    cancel() {},
    speak(utterance) { queueMicrotask(() => { utterance.onstart?.(); utterance.onend?.() }) },
  })
  install('SpeechSynthesisUtterance', class { constructor(text) { this.text = text } })
  const audioNode = () => ({ connect() {}, disconnect() {}, gain: { value: 0, exponentialRampToValueAtTime() {} } })
  install('AudioContext', class {
    sampleRate = 48000
    currentTime = 0
    destination = {}
    createMediaStreamSource() { return audioNode() }
    createScriptProcessor() { return audioNode() }
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
    server: { middlewareMode: true, hmr: false, ws: false },
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
  async function waitFor(condition) {
    for (let i = 0; i < 100; i++) {
      await pause()
      if (condition()) return
    }
    assert.fail('UI did not reach the expected state')
  }
  const click = async element => act(async () => { element.click() })
  async function setup() {
    const calls = []
    let micCalls = 0
    let stoppedTracks = 0
    let microphone = async () => ({ getTracks: () => [{ stop() { stoppedTracks++ } }] })
    let speechResponse = async () => Response.json({ rawText: '音声回答', maskedText: '音声回答' })
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
      getUserMedia() { micCalls++; return microphone() },
    } })
    const payload = {
      session: { id: 'test', language: 'ja', status: 'running', title: 'test' },
      messages: [{ id: 'opening', role: 'system', content: '？' }],
      state: { turn_count: 0 }, stateLabel: 'running',
    }
    install('fetch', async (path, options = {}) => {
      calls.push({ path, options })
      if (path === '/api/me') return Response.json({ account: { id: 'operator', role: 'operator', displayName: 'テスト' } })
      if (path === '/api/sessions' && options.method !== 'POST') return Response.json({ sessions: [] })
      if (path === '/api/local/mask-text') return Response.json({ maskedText: JSON.parse(options.body).text })
      if (path === '/api/speech/transcribe') return speechResponse()
      if (path.endsWith('/messages')) {
        const body = JSON.parse(options.body)
        payload.messages.push({ id: 'answer', role: 'user', content: body.maskedText },
          { id: 'reply', role: 'system', content: '？' })
      }
      return Response.json(payload)
    })
    recorders.length = 0
    const root = createRoot(document.getElementById('root'))
    await act(async () => { root.render(createElement(App)) })
    await waitFor(() => document.querySelector('.new-session'))
    await click(document.querySelector('.new-session'))
    await waitFor(() => document.querySelector('textarea'))
    await pause(150)
    return {
      calls,
      get micCalls() { return micCalls },
      get stoppedTracks() { return stoppedTracks },
      setMicrophone(fn) { microphone = fn },
      setSpeechResponse(fn) { speechResponse = fn },
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
