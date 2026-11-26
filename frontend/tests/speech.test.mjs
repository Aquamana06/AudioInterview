import assert from 'node:assert/strict'
import test from 'node:test'
import { pcmToWav, transcribeAudio } from '../src/speech.ts'

for (const [mime, extension] of [['audio/webm;codecs=opus', 'webm'], ['audio/wav', 'wav'], ['audio/mp4', 'mp4'], ['audio/ogg', 'ogg']]) {
  test(`uploads ${mime} with authentication and language`, async t => {
    const previous = globalThis.fetch
    t.after(() => { globalThis.fetch = previous })
    globalThis.fetch = async (path, options) => {
      assert.equal(path, '/api/speech/transcribe')
      assert.equal(options.method, 'POST')
      assert.equal(options.credentials, 'same-origin')
      assert.equal(options.body.get('language'), 'ja')
      assert.equal(options.body.get('sessionId'), null)
      assert.equal(options.body.get('recordingId'), null)
      const audio = options.body.get('audio')
      assert.equal(audio.name, `recording.${extension}`)
      assert.equal(await audio.text(), 'recorded audio')
      assert.equal(options.headers, undefined) // Browser supplies multipart boundary.
      return Response.json({ rawText: '塩酸を確認', normalizedText: '塩酸を確認', maskedText: '薬品Aを確認', endOfTurn: false })
    }
    const result = await transcribeAudio(new Blob(['recorded audio'], { type: mime }), 'ja')
    assert.equal(result.maskedText, '薬品Aを確認')
  })
}

test('final recording includes the session and stable recording ID for server storage', async t => {
  const previous = globalThis.fetch
  t.after(() => { globalThis.fetch = previous })
  globalThis.fetch = async (_path, options) => {
    assert.equal(options.body.get('sessionId'), 'interview_001')
    assert.equal(options.body.get('recordingId'), 'recording_001')
    return Response.json({ rawText: '回答', maskedText: '回答', recordingId: 'recording_001', audioFile: 'audio/recording_001.ogg' })
  }
  const result = await transcribeAudio(new Blob(['answer'], { type: 'audio/ogg' }), 'ja', {
    sessionId: 'interview_001', recordingId: 'recording_001',
  })
  assert.equal(result.audioFile, 'audio/recording_001.ogg')
})

test('reports server errors to the caller', async t => {
  const previous = globalThis.fetch
  t.after(() => { globalThis.fetch = previous })
  globalThis.fetch = async () => Response.json({ error: 'Authentication required' }, { status: 401 })
  await assert.rejects(transcribeAudio(new Blob(['audio']), 'en'), /Authentication required/)
})

test('encodes rolling microphone samples as a PCM WAV for the server', async () => {
  const wav = pcmToWav(new Float32Array([-1, 0, 1]), 48000)
  const view = new DataView(await wav.arrayBuffer())
  assert.equal(wav.type, 'audio/wav')
  assert.equal(view.getUint32(24, true), 48000)
  assert.equal(view.getUint32(40, true), 6)
  assert.equal(view.getInt16(44, true), -32768)
  assert.equal(view.getInt16(48, true), 32767)
})

test('wake word accepts Japanese and English calls while ignoring ordinary conversation', async () => {
  const { isWakeWord } = await import('../src/wakeWord.ts')
  for (const word of ['ヘイウィスパー', 'ヘイ、ウィスパー。', 'ヘイ ウイスパー', 'Hey Whisper!', 'heywhisper', 'へい、うぃすぱー']) {
    assert.equal(isWakeWord(word), true, word)
  }
  for (const words of ['', 'whisper', 'hey', '今日は晴れです', 'ヘイウィスパーと言いました', 'They whisper']) {
    assert.equal(isWakeWord(words), false, words)
  }
})
