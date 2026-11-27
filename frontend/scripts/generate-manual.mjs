// Capture the real UI with sample API responses; never access interview records.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { createServer } from 'vite'
import { manualContent } from '../src/manualContent.ts'
import { manualDocument } from './manual-document.mjs'

const frontend = fileURLToPath(new URL('..', import.meta.url))
const output = path.join(frontend, 'public/manual')
const documentation = path.resolve(frontend, '../docs/operation-manual')
await mkdir(output, { recursive: true })
await mkdir(documentation, { recursive: true })
const server = await createServer({ root: frontend, server: { host: '127.0.0.1', port: 0 } })
let browser
try {
  await server.listen()
  const address = server.httpServer.address()
  const origin = `http://127.0.0.1:${address.port}`
  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 430, height: 860 }, deviceScaleFactor: 2 })
  const account = { id: 'sample_operator', role: 'operator', displayName: '操作説明用', manualAcknowledged: false }
  let loggedIn = false
  let payload = null
  let sessionCreations = 0
  const sessionHistory = []
  await page.addInitScript(() => {
    window.SpeechRecognition = class {
      constructor() { window.__manualRecognition = this }
      start() { this.active = true }
      abort() { this.active = false }
    }
    window.webkitSpeechRecognition = undefined
    Object.defineProperty(window, 'speechSynthesis', { value: {
      paused: false, cancel() {}, getVoices: () => [],
      pause() { this.paused = true }, resume() { this.paused = false },
      speak(utterance) { queueMicrotask(() => { utterance.onstart?.(); utterance.onend?.() }) },
    } })
    const node = () => ({ connect() {}, disconnect() {}, gain: { value: 0, exponentialRampToValueAtTime() {} } })
    window.AudioContext = class {
      sampleRate = 48000; currentTime = 0; destination = {}
      createMediaStreamSource() { return node() }
      createScriptProcessor() { return node() }
      createGain() { return node() }
      createOscillator() { return { ...node(), frequency: {}, start() {}, stop() {} } }
      async resume() {} async close() {}
    }
    window.__manualRecorders = []
    window.MediaRecorder = class {
      state = 'inactive'; mimeType = 'audio/webm'
      constructor() { window.__manualRecorders.push(this) }
      start() { this.state = 'recording' }
      pause() { this.state = 'paused' }
      resume() { this.state = 'recording' }
      stop() { this.state = 'inactive'; this.ondataavailable?.({ data: new Blob(['sample audio']) }); this.onstop?.() }
    }
    Object.defineProperty(navigator, 'mediaDevices', { value: {
      getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
    } })
  })
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url()).pathname
    const json = (body, status = 200) => route.fulfill({ status, json: body })
    if (url === '/api/me') return loggedIn ? json({ account }) : json({ error: 'Authentication required' }, 401)
    if (url === '/api/auth/login') { loggedIn = true; return json({ account }) }
    if (url === '/api/me/manual') { account.manualAcknowledged = true; return json({ account }) }
    if (url === '/api/sessions' && request.method() === 'GET') return json({ sessions: sessionHistory.map(session => ({
      ...session, memory_status: session.id === payload?.session.id ? payload.memory.status : 'ready',
    })) })
    if (url === '/api/sessions' && request.method() === 'POST') {
      sessionCreations++
      payload = {
        session: { id: sessionCreations === 1 ? 'manual_sample' : `manual_sample_${sessionCreations}`, account_id: account.id, title: '操作説明用', language: 'ja', status: 'running' },
        messages: [], state: { turn_count: 0 }, stateLabel: 'running', memory: { status: 'not_started', summary: null },
      }
      sessionHistory.push(payload.session)
      return json(payload)
    }
    if (url.endsWith('/start')) {
      payload.messages = [{ id: 'opening', role: 'system', content: '直前まで、どのようなお仕事をしていましたか？' }]
      return json(payload)
    }
    if (url === '/api/local/mask-text') return json({ maskedText: request.postDataJSON().text })
    if (url.endsWith('/messages')) {
      payload.messages.push({ id: 'answer', role: 'user', content: request.postDataJSON().maskedText },
        { id: 'question', role: 'system', content: 'その作業で工夫したことを教えてください。' })
      return json(payload)
    }
    if (url.endsWith('/end')) {
      payload.session.status = 'ended'
      payload.stateLabel = 'end'
      payload.memory.status = 'pending'
      payload.messages.push({ id: 'ending', role: 'system', content: 'ありがとうございました。これでインタビューを終了します。' })
      return json(payload)
    }
    if (url === `/api/sessions/${payload?.session.id}`) return json(payload)
    return json({ error: `Unexpected sample route: ${url}` }, 404)
  })
  async function capture(name, target) {
    const locator = page.locator(target)
    await locator.waitFor({ state: 'visible' })
    const send = page.locator('.composer-actions .send')
    if (await send.count()) {
      const actionsBox = await page.locator('.composer-actions').boundingBox()
      const sendBox = await send.boundingBox()
      assert.ok(sendBox.width < actionsBox.width / 2, 'send must remain a compact button')
      assert.ok(Math.abs(sendBox.x + sendBox.width - actionsBox.x - actionsBox.width) < 1, 'send must align to the right')
    }
    await page.locator('.interview-layout').screenshot({ path: path.join(output, name) })
  }
  await page.goto(origin)
  await page.locator('.login-card').waitFor()
  await page.locator('.login-card input').first().fill('sample_operator')
  await page.locator('.login-card').screenshot({ path: path.join(output, 'login.png') })
  await page.locator('.login-card button[type=submit], .login-card .primary').click()
  await page.locator('.manual-dialog').waitFor()
  assert.equal(sessionCreations, 0, 'onboarding must not create an interview')
  await page.locator('.manual-footer button').click()
  await page.locator('.manual-dialog').waitFor({ state: 'hidden' })
  await capture('start.png', '.composer')
  await page.getByRole('button', { name: 'インタビューを開始', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.assistant-bubble p')?.textContent === '直前まで、どのようなお仕事をしていましたか？')
  await page.locator('.handsfree-button').screenshot({ path: path.join(output, 'voice-button.png') })
  await page.locator('.handsfree-button').click()
  await page.waitForFunction(() => window.__manualRecorders[0]?.state === 'recording')
  assert.equal(await page.locator('.recording-indicator').textContent(), '録音中')
  assert.equal(await page.locator('.handsfree-button').textContent(), '停止して送信')
  assert.ok(await page.locator('.handsfree-button').evaluate(button => parseFloat(getComputedStyle(button).borderTopWidth) > 0), 'stop and send must have a visible button border')
  await capture('voice.png', '.composer')
  // Verify the real browser keeps the same MediaRecorder and interview mounted.
  await page.locator('.interview-utilities .manual-trigger').click()
  await page.waitForFunction(() => window.__manualRecorders[0].state === 'paused')
  await page.locator('.manual-close').click()
  await page.waitForFunction(() => window.__manualRecorders[0].state === 'recording')
  assert.equal(await page.evaluate(() => window.__manualRecorders.length), 1)
  await page.locator('textarea').fill('設備の点検をしていました。')
  await capture('text.png', '.composer')
  const creationsBeforeHelp = sessionCreations
  await page.locator('.interview-utilities .manual-trigger').click()
  await page.locator('.manual-close').click()
  assert.equal(await page.locator('textarea').inputValue(), '設備の点検をしていました。')
  assert.equal(sessionCreations, creationsBeforeHelp)
  await page.getByRole('button', { name: '送信', exact: true }).click()
  await page.getByRole('button', { name: 'インタビューを終了', exact: true }).click()
  await page.locator('.saving-screen').waitFor()
  await capture('end.png', '.saving-screen')
  payload.memory.status = 'ready'
  await page.waitForFunction(() => {
    const button = document.querySelector('.start-interview')
    return button && !button.disabled
  })
  await capture('repeat.png', '.start-interview')
  await page.waitForFunction(() => window.__manualRecognition?.active)
  await page.evaluate(() => window.__manualRecognition.onresult({
    resultIndex: 0, results: [{ isFinal: true, 0: { transcript: 'ヘイウィスパー' } }],
  }))
  await page.waitForFunction(() => document.querySelector('.interview-layout:not(.standby)'))
  assert.equal(sessionCreations, 2, 'a wake word must start the second interview without logging in again')
  assert.equal(await page.locator('.manual-dialog').count(), 0)

  // Use the same text in the site and PDF, with full-screen captures on print pages.
  const pdfPage = await browser.newPage({ viewport: { width: 688, height: 1024 } })
  await pdfPage.setContent(await manualDocument(output))
  await pdfPage.evaluate(() => document.fonts.ready)
  await pdfPage.emulateMedia({ media: 'print' })
  const printHeights = await pdfPage.locator('.print-page').evaluateAll(pages => pages.map(page => page.getBoundingClientRect().height))
  assert.ok(printHeights.every(height => height <= 1024), `A4 pages must not overflow: ${printHeights.join(', ')}`)
  const pdfPath = path.join(output, 'interview-manual.pdf')
  await pdfPage.pdf({ path: pdfPath, format: 'A4', printBackground: true, preferCSSPageSize: true, tagged: true })
  await pdfPage.screenshot({ path: path.join(documentation, 'pdf-preview.png'), fullPage: true })
  await writeFile(path.join(documentation, 'manual-text.md'), [
    `# ${manualContent.title}`, '', manualContent.introduction, '',
    `## ${manualContent.preparation.title}`, '', manualContent.preparation.browser, '',
    ...manualContent.preparation.instructions.map((instruction, index) => `${index + 1}. ${instruction}`), '', manualContent.preparation.note, '',
    ...manualContent.patterns.flatMap(pattern => [`## ${pattern.title}`, '',
      ...pattern.steps.flatMap((step, index) => [`### ${index + 1}. ${step.title}`, '', `**${step.keyPoint}**`, '', step.text, '', ...(step.note ? [step.note, ''] : [])])]),
    `## ${manualContent.repeat.title}`, '', manualContent.repeat.text, '', manualContent.repeat.callout, '', manualContent.repeat.availability, '',
    '## こんなときは？', '',
    ...manualContent.questions.flatMap(item => [`### ${item.question}`, '', item.answer, '', ...item.instructions.map((instruction, index) => `${index + 1}. ${instruction}`), '', item.note, '']),
    manualContent.help, '',
  ].join('\n'))

  // Refresh assets in the existing page, then inspect the modal at both sizes.
  await page.locator('.interview-utilities .manual-trigger').click()
  await page.locator('.manual-dialog img').evaluateAll(images => Promise.all(images.map(image => image.decode())))
  assert.deepEqual(await page.locator('.manual-questions > h2').allTextContents(), ['こんなときは？'])
  assert.deepEqual(await page.locator('.manual-questions summary').allTextContents(), manualContent.questions.map(item => item.question))
  assert.equal(await page.locator('.manual-pattern').count(), manualContent.patterns.length)
  for (const [index, pattern] of (await page.locator('.manual-pattern').all()).entries()) {
    assert.deepEqual(await pattern.locator('.manual-steps h3').allTextContents(), manualContent.patterns[index].steps.map((step, stepIndex) => `${stepIndex + 1}${step.title}`))
  }
  assert.equal(await page.locator('.manual-steps a img').count(), manualContent.patterns.reduce((count, pattern) => count + pattern.steps.length, 0))
  await page.screenshot({ path: path.join(documentation, 'mobile-preview.png') })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.screenshot({ path: path.join(documentation, 'site-preview.png') })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  assert.equal(overflow, false, 'manual must fit the viewport')
  await page.locator('.manual-close').click()
  await page.reload()
  await page.locator('.interview-layout:not(.standby)').waitFor()
  assert.equal(await page.locator('.manual-dialog').count(), 0, 'acknowledged guide must not reopen after reload')
  console.log(`Screenshots: ${output}\nPDF: ${pdfPath}\nBrowser checks: onboarding, recording pause/resume, draft preservation, repeated interviews by wake word, responsive modal, reload.`)
} finally {
  await browser?.close()
  await server.close()
}
