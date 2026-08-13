import type { Account, ApiMessage, InterviewSession, InterviewState, Language, MessageRow, RuntimeEnv } from './types.js';

export const jsonHeaders = {
  'content-type': 'application/json; charset=utf-8',
};

export function json(data: unknown, init: ResponseInit = {}) {
  return new Response(JSON.stringify(data), {
    ...init,
    headers: { ...jsonHeaders, ...(init.headers ?? {}) },
  });
}

export function error(message: string, status = 400) {
  return json({ error: message }, { status });
}

export async function readJson<T>(request: Request): Promise<T> {
  try {
    return (await request.json()) as T;
  } catch {
    throw new HttpError('Invalid JSON body', 400);
  }
}

export class HttpError extends Error {
  status: number;

  constructor(message: string, status = 400) {
    super(message);
    this.status = status;
  }
}

export function randomId(prefix: string) {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${prefix}_${value}`;
}

export function nowIso() {
  return new Date().toISOString();
}

export function mapMessage(row: MessageRow): ApiMessage {
  return {
    id: row.id,
    role: row.role,
    content: row.content,
    inputMode: row.input_mode,
    language: row.language,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export async function ensureAdmin(env: RuntimeEnv) {
  const existing = await env.RI_db.prepare('SELECT id FROM accounts WHERE id = ?').bind('admin').first();
  if (existing) return;

  const salt = randomId('salt');
  const passwordHash = await hashPassword('admin', salt);
  await env.RI_db.prepare(
    `INSERT INTO accounts (id, role, display_name, password_hash, password_salt)
     VALUES (?, 'admin', 'Administrator', ?, ?)`,
  )
    .bind('admin', passwordHash, salt)
    .run();
}

export async function hashPassword(password: string, salt: string) {
  const bytes = new TextEncoder().encode(`${salt}:${password}`);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function getAccount(env: RuntimeEnv, id: string) {
  return env.RI_db.prepare('SELECT * FROM accounts WHERE id = ? AND is_active = 1').bind(id).first<Account>();
}

export async function createAuthSession(env: RuntimeEnv, accountId: string) {
  const token = randomId('sess');
  const expires = new Date(Date.now() + 1000 * 60 * 60 * 24 * 14).toISOString();
  await env.RI_db.prepare('INSERT INTO auth_sessions (token, account_id, expires_at) VALUES (?, ?, ?)')
    .bind(token, accountId, expires)
    .run();
  return token;
}

export async function deleteAuthSession(env: RuntimeEnv, token: string) {
  await env.RI_db.prepare('DELETE FROM auth_sessions WHERE token = ?').bind(token).run();
}

export async function getSessionAccount(env: RuntimeEnv, token: string) {
  return env.RI_db.prepare(
    `SELECT accounts.*
     FROM auth_sessions
     JOIN accounts ON accounts.id = auth_sessions.account_id
     WHERE auth_sessions.token = ? AND auth_sessions.expires_at > ? AND accounts.is_active = 1`,
  )
    .bind(token, nowIso())
    .first<Account>();
}

export async function insertMessage(
  env: RuntimeEnv,
  sessionId: string,
  role: 'system' | 'user',
  content: string,
  inputMode: 'text' | 'voice' | 'system',
  language: Language,
  meta?: unknown,
) {
  const id = randomId(role === 'user' ? 'usr' : 'sys');
  await env.RI_db.prepare(
    `INSERT INTO messages (id, session_id, role, content, input_mode, language, meta_json)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(id, sessionId, role, content, inputMode, language, meta ? JSON.stringify(meta) : null)
    .run();
  return id;
}

export async function updateState(env: RuntimeEnv, sessionId: string, state: InterviewState, label: 'running' | 'end') {
  await env.RI_db.prepare(
    `INSERT INTO interview_states (session_id, state_json, state_label, updated_at)
     VALUES (?, ?, ?, ?)
     ON CONFLICT(session_id) DO UPDATE SET
       state_json = excluded.state_json,
       state_label = excluded.state_label,
       updated_at = excluded.updated_at`,
  )
    .bind(sessionId, JSON.stringify(state), label, nowIso())
    .run();
}

export async function getState(env: RuntimeEnv, sessionId: string) {
  const row = await env.RI_db.prepare('SELECT state_json, state_label FROM interview_states WHERE session_id = ?')
    .bind(sessionId)
    .first<{ state_json: string; state_label: 'running' | 'end' }>();
  if (!row) return null;
  return { state: JSON.parse(row.state_json) as InterviewState, stateLabel: row.state_label };
}

export async function listMessages(env: RuntimeEnv, sessionId: string) {
  const { results } = await env.RI_db.prepare('SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC')
    .bind(sessionId)
    .all<MessageRow>();
  return results;
}

export async function getOwnedSession(env: RuntimeEnv, sessionId: string, accountId: string, isAdmin: boolean) {
  const query = isAdmin
    ? 'SELECT * FROM interview_sessions WHERE id = ?'
    : 'SELECT * FROM interview_sessions WHERE id = ? AND account_id = ?';
  const stmt = isAdmin ? env.RI_db.prepare(query).bind(sessionId) : env.RI_db.prepare(query).bind(sessionId, accountId);
  return stmt.first<InterviewSession>();
}
