export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeout = globalThis.setTimeout(() => controller.abort(), 90_000)
  try {
    const response = await fetch(path, { credentials: 'same-origin', ...init, signal: init?.signal ?? controller.signal })
    const data = await response.json().catch(() => ({})) as T & { error?: string }
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`)
    return data
  } finally {
    globalThis.clearTimeout(timeout)
  }
}
