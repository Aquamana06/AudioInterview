export type Workspace = {
  sessionId: string | null
  view: 'admin' | 'interview'
  language: 'ja' | 'en' | 'de'
  voice: boolean
  pendingStartId: string | null
}

const key = (accountId: string) => `audiointerview.workspace.${accountId}`

export function readWorkspace(accountId: string): Workspace | null {
  try {
    const value = JSON.parse(window.localStorage.getItem(key(accountId)) ?? 'null')
    if (!value || !['admin', 'interview'].includes(value.view) || !['ja', 'en', 'de'].includes(value.language)) return null
    return {
      sessionId: typeof value.sessionId === 'string' ? value.sessionId : null,
      view: value.view, language: value.language, voice: value.voice === true,
      pendingStartId: typeof value.pendingStartId === 'string' ? value.pendingStartId : null,
    }
  } catch { return null }
}

export function saveWorkspace(accountId: string, value: Workspace): void {
  try { window.localStorage.setItem(key(accountId), JSON.stringify(value)) }
  catch { /* Login and server-side interview records remain available without local storage. */ }
}

export function clearWorkspace(accountId: string): void {
  try { window.localStorage.removeItem(key(accountId)) } catch { /* Storage may be disabled. */ }
}
