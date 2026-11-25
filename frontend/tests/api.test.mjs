import assert from 'node:assert/strict'
import test from 'node:test'
import { api, ApiError } from '../src/api.ts'

const stalledFetch = (_path, { signal }) => new Promise((_, reject) => {
  if (signal.aborted) reject(signal.reason)
  else signal.addEventListener('abort', () => reject(signal.reason), { once: true })
})

test('API timeouts work with a caller signal and leave authentication untouched', async t => {
  t.mock.method(globalThis, 'fetch', stalledFetch)
  const caller = new AbortController()
  await assert.rejects(api('/api/me', { signal: caller.signal }, 15), /サーバーからの応答がありません/)
  assert.equal(caller.signal.aborted, false)
})

test('caller cancellation still stops an API request', async t => {
  t.mock.method(globalThis, 'fetch', stalledFetch)
  const caller = new AbortController()
  const request = api('/api/me', { signal: caller.signal })
  caller.abort()
  await assert.rejects(request, { name: 'AbortError' })
})

test('API failures preserve HTTP status so expired authentication can be handled separately', async t => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({ error: 'Authentication required' }, { status: 401 }))
  await assert.rejects(api('/api/me'), error => error instanceof ApiError && error.status === 401)
})
