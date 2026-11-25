export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, init?: RequestInit, timeoutMs = 90_000): Promise<T> {
  const controller = new AbortController()
  let timedOut = false
  const abort = () => controller.abort(init?.signal?.reason)
  if (init?.signal?.aborted) abort()
  else init?.signal?.addEventListener('abort', abort, { once: true })
  const timeout = globalThis.setTimeout(() => { timedOut = true; controller.abort() }, timeoutMs)
  try {
    const response = await fetch(path, { credentials: 'same-origin', ...init, signal: controller.signal })
    const data = await response.json().catch(error => {
      if (controller.signal.aborted) throw error
      return {}
    }) as T & { error?: string }
    if (!response.ok) throw new ApiError(data.error || `Request failed (${response.status})`, response.status)
    return data
  } catch (error) {
    if (timedOut) throw new Error('サーバーからの応答がありません。接続を確認して再試行してください。')
    throw error
  } finally {
    globalThis.clearTimeout(timeout)
    init?.signal?.removeEventListener('abort', abort)
  }
}
