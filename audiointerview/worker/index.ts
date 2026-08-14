import { clearAuthCookie, authCookie, login, logout, publicAccount, readCookie, requireAdmin, requireAuth } from './auth.js';
import { endings, firstUtterance, initialState, runInterviewTurn } from './agent.js';
import {
  error,
  getOwnedSession,
  getState,
  hashPassword,
  HttpError,
  insertMessage,
  json,
  listMessages,
  mapMessage,
  nowIso,
  randomId,
  readJson,
  updateState,
} from './db.js';
import { openaiStatus } from './openai.js';
import {
  applyProfileUpdate,
  extractAndUpdateProfile,
  finalizeSessionMemory,
  getWorkerContext,
  interviewTransition,
  needsProfileBuilding,
  nextProfileQuestion,
  persistExtractedMemories,
  profileOpening,
} from './memory.js';
import type { InputMode, InterviewSession, Language, RuntimeEnv } from './types.js';

const languages = new Set<Language>(['ja', 'en', 'de']);
const jsonBody = <T>(request: Request) => readJson<T>(request);

function language(value: unknown): Language {
  return typeof value === 'string' && languages.has(value as Language) ? (value as Language) : 'ja';
}

function cookieResponse(data: unknown, cookie: string, status = 200) {
  return json(data, { status, headers: { 'set-cookie': cookie } });
}

async function sessionPayload(env: RuntimeEnv, session: InterviewSession) {
  const messages = await listMessages(env, session.id);
  const savedState = await getState(env, session.id);
  const workerContext = await getWorkerContext(env, session.account_id);
  return {
    session,
    messages: messages.map(mapMessage),
    state: savedState?.state ?? initialState(),
    stateLabel: savedState?.stateLabel ?? 'running',
    workerProfile: workerContext.profile,
    longTermMemories: workerContext.memories,
    sessionSummary: workerContext.recentSessionSummaries.find((item) => item.sessionId === session.id) ?? null,
  };
}

async function processMessage(
  env: RuntimeEnv,
  session: InterviewSession,
  content: string,
  inputMode: InputMode,
) {
  const saved = await getState(env, session.id);
  const state = saved?.state ?? initialState();
  const history = await listMessages(env, session.id);
  const userMessageId = await insertMessage(env, session.id, 'user', content, inputMode, session.language);

  if (session.phase === 'profile') {
    const profile = await extractAndUpdateProfile(env, session.account_id, content, userMessageId);
    const profileTurnCount = session.profile_turn_count + 1;
    const profileDone = profileTurnCount >= 8 || (profileTurnCount >= 3 && !needsProfileBuilding(profile));
    const text = profileDone
      ? interviewTransition(session.language)
      : await nextProfileQuestion(env, profile, content, session.language);
    await insertMessage(env, session.id, 'system', text, 'system', session.language, {
      phase: 'profile', profileSnapshot: profile, profileDone,
    });
    await env.RI_db.prepare('UPDATE interview_sessions SET phase = ?, profile_turn_count = ?, updated_at = ? WHERE id = ?')
      .bind(profileDone ? 'interview' : 'profile', profileTurnCount, nowIso(), session.id).run();
    return sessionPayload(env, { ...session, phase: profileDone ? 'interview' : 'profile', profile_turn_count: profileTurnCount });
  }

  const currentHistory = await listMessages(env, session.id);
  const workerContext = await getWorkerContext(env, session.account_id);
  const result = await runInterviewTurn(env, state, content, currentHistory, session.language, workerContext);
  await applyProfileUpdate(env, session.account_id, result.extracted.profile_update, userMessageId);
  await insertMessage(env, session.id, 'system', result.text, 'system', session.language, {
    extracted: result.extracted,
    guide: result.guide,
    stateSnapshot: result.state,
  });
  await updateState(env, session.id, result.state, result.stateLabel);
  await persistExtractedMemories(env, session.account_id, session.id, userMessageId, result.extracted);
  await env.RI_db.prepare('UPDATE interview_sessions SET updated_at = ? WHERE id = ?').bind(nowIso(), session.id).run();
  if (result.stateLabel === 'end') {
    await env.RI_db.prepare("UPDATE interview_sessions SET status = 'ended', ended_at = ?, updated_at = ? WHERE id = ?")
      .bind(nowIso(), nowIso(), session.id)
      .run();
    await finalizeSessionMemory(env, session.account_id, session.id, result.state);
  }
  return { ...(await sessionPayload(env, { ...session, status: result.stateLabel === 'end' ? 'ended' : session.status })), correctedMaskedText: result.correctedMaskedText, previousMessageCount: history.length };
}

async function replayAfterEdit(env: RuntimeEnv, session: InterviewSession, messageId: string, content: string) {
  const rows = await listMessages(env, session.id);
  const editIndex = rows.findIndex((row) => row.id === messageId && row.role === 'user');
  if (editIndex < 0) throw new HttpError('Editable user message not found', 404);
  const retained = rows.slice(0, editIndex);
  await env.RI_db.prepare('DELETE FROM messages WHERE session_id = ? AND created_at >= ?').bind(session.id, rows[editIndex].created_at).run();
  await env.RI_db.prepare('DELETE FROM interview_states WHERE session_id = ?').bind(session.id).run();

  let state = initialState();
  const userTurns = [...retained.filter((row) => row.role === 'user'), { ...rows[editIndex], content }];
  const rebuilt = retained.filter((row) => row.role === 'system').slice(0, 1);
  await env.RI_db.prepare('DELETE FROM messages WHERE session_id = ?').bind(session.id).run();
  if (rebuilt.length) await insertMessage(env, session.id, 'system', rebuilt[0].content, 'system', session.language);

  for (const turn of userTurns) {
    await insertMessage(env, session.id, 'user', turn.content, turn.input_mode, session.language);
    const history = await listMessages(env, session.id);
    const workerContext = await getWorkerContext(env, session.account_id);
    const result = await runInterviewTurn(env, state, turn.content, history, session.language, workerContext);
    state = result.state;
    await insertMessage(env, session.id, 'system', result.text, 'system', session.language, {
      extracted: result.extracted,
      guide: result.guide,
      stateSnapshot: result.state,
    });
  }
  await updateState(env, session.id, state, 'running');
  await env.RI_db.prepare("UPDATE interview_sessions SET status = 'running', ended_at = NULL, updated_at = ? WHERE id = ?")
    .bind(nowIso(), session.id)
    .run();
  return sessionPayload(env, { ...session, status: 'running', ended_at: null });
}

async function handleApi(request: Request, env: RuntimeEnv) {
  const url = new URL(request.url);
  const path = url.pathname;

  if (request.method === 'GET' && path === '/api/status') return json(await openaiStatus(env));

  if (request.method === 'POST' && path === '/api/auth/login') {
    const body = await jsonBody<{ id?: string; password?: string; qrToken?: string }>(request);
    const id = (body.id || body.qrToken || '').replace(/^audiointerview:\/\/login\?id=/, '');
    if (!id) throw new HttpError('ID is required');
    const result = await login(env, decodeURIComponent(id), body.password);
    return cookieResponse({ account: result.account }, authCookie(request, result.token));
  }

  if (request.method === 'POST' && path === '/api/auth/logout') {
    await logout(env, readCookie(request, 'ai_session'));
    return cookieResponse({ ok: true }, clearAuthCookie(request));
  }

  if (request.method === 'GET' && path === '/api/me') {
    const auth = await requireAuth(request, env);
    return json({ account: publicAccount(auth.account) });
  }

  if (request.method === 'GET' && path === '/api/profile') {
    const auth = await requireAuth(request, env);
    return json(await getWorkerContext(env, auth.account.id));
  }

  const workerContextMatch = path.match(/^\/api\/workers\/([^/]+)\/context$/);
  if (request.method === 'GET' && workerContextMatch) {
    await requireAdmin(request, env);
    return json(await getWorkerContext(env, decodeURIComponent(workerContextMatch[1])));
  }

  if (request.method === 'PUT' && path === '/api/me/password') {
    const auth = await requireAdmin(request, env);
    const body = await jsonBody<{ password?: string }>(request);
    if (!body.password || body.password.length < 6) throw new HttpError('Password must be at least 6 characters');
    const salt = randomId('salt');
    const passwordHash = await hashPassword(body.password, salt);
    await env.RI_db.prepare('UPDATE accounts SET password_hash = ?, password_salt = ?, updated_at = ? WHERE id = ?')
      .bind(passwordHash, salt, nowIso(), auth.account.id)
      .run();
    return json({ ok: true });
  }

  if (request.method === 'GET' && path === '/api/sessions') {
    const auth = await requireAuth(request, env);
    const statement = auth.account.role === 'admin'
      ? env.RI_db.prepare('SELECT * FROM interview_sessions ORDER BY updated_at DESC')
      : env.RI_db.prepare('SELECT * FROM interview_sessions WHERE account_id = ? ORDER BY updated_at DESC').bind(auth.account.id);
    const { results } = await statement.all<InterviewSession>();
    return json({ sessions: results });
  }

  if (request.method === 'POST' && path === '/api/sessions') {
    const auth = await requireAuth(request, env);
    const body = await jsonBody<{ language?: Language; title?: string }>(request);
    const lang = language(body.language);
    const id = randomId('interview');
    const title = body.title?.trim() || `Interview ${new Date().toLocaleDateString('ja-JP')}`;
    const priorSession = await env.RI_db.prepare('SELECT id FROM interview_sessions WHERE account_id = ? LIMIT 1')
      .bind(auth.account.id).first();
    const phase = priorSession ? 'interview' : 'profile';
    await env.RI_db.prepare('INSERT INTO interview_sessions (id, account_id, title, language, phase) VALUES (?, ?, ?, ?, ?)')
      .bind(id, auth.account.id, title, lang, phase)
      .run();
    const session = await getOwnedSession(env, id, auth.account.id, auth.account.role === 'admin');
    return json(await sessionPayload(env, session!), { status: 201 });
  }

  const sessionMatch = path.match(/^\/api\/sessions\/([^/]+)(?:\/(start|messages|end))?$/);
  if (sessionMatch) {
    const auth = await requireAuth(request, env);
    const session = await getOwnedSession(env, sessionMatch[1], auth.account.id, auth.account.role === 'admin');
    if (!session) throw new HttpError('Session not found', 404);
    const action = sessionMatch[2];
    if (request.method === 'GET' && !action) return json(await sessionPayload(env, session));
    if (request.method === 'POST' && action === 'start') {
      const existing = await listMessages(env, session.id);
      if (!existing.length) {
        const opening = session.phase === 'profile' ? profileOpening(session.language) : firstUtterance(session.language);
        await insertMessage(env, session.id, 'system', opening, 'system', session.language, { stateSnapshot: initialState() });
        await updateState(env, session.id, initialState(), 'running');
      }
      return json(await sessionPayload(env, session));
    }
    if (request.method === 'POST' && action === 'messages') {
      if (session.status === 'ended') throw new HttpError('Session has ended', 409);
      const body = await jsonBody<{ maskedText?: string; inputMode?: InputMode; editMessageId?: string }>(request);
      const content = body.maskedText?.trim();
      if (!content) throw new HttpError('maskedText is required');
      if (body.editMessageId) return json(await replayAfterEdit(env, session, body.editMessageId, content));
      return json(await processMessage(env, session, content, body.inputMode === 'voice' ? 'voice' : 'text'));
    }
    if (request.method === 'POST' && action === 'end') {
      if (session.status !== 'ended') {
        await insertMessage(env, session.id, 'system', endings[session.language], 'system', session.language);
        await env.RI_db.prepare("UPDATE interview_sessions SET status = 'ended', ended_at = ?, updated_at = ? WHERE id = ?")
          .bind(nowIso(), nowIso(), session.id)
          .run();
        const saved = await getState(env, session.id);
        await updateState(env, session.id, saved?.state ?? initialState(), 'end');
        await finalizeSessionMemory(env, session.account_id, session.id, saved?.state ?? initialState());
      }
      return json(await sessionPayload(env, { ...session, status: 'ended', ended_at: nowIso() }));
    }
  }

  if (request.method === 'POST' && path === '/api/speech/transcribe') {
    await requireAuth(request, env);
    const backend = env.LOCAL_INTERVIEW_BACKEND_URL ?? 'http://127.0.0.1:8000';
    const response = await fetch(`${backend}/transcribe`, { method: 'POST', body: await request.formData() });
    return new Response(response.body, { status: response.status, headers: { 'content-type': response.headers.get('content-type') ?? 'application/json' } });
  }

  if (path === '/api/admin/accounts') {
    await requireAdmin(request, env);
    if (request.method === 'GET') {
      const { results } = await env.RI_db.prepare('SELECT id, role, display_name, is_active, created_at FROM accounts ORDER BY created_at DESC').all();
      return json({ accounts: results });
    }
    if (request.method === 'POST') {
      const body = await jsonBody<{ id?: string; displayName?: string }>(request);
      const id = body.id?.trim() || randomId('operator').slice(0, 17);
      if (!/^[A-Za-z0-9_-]{3,40}$/.test(id)) throw new HttpError('ID must be 3-40 letters, numbers, _ or -');
      await env.RI_db.prepare("INSERT INTO accounts (id, role, display_name) VALUES (?, 'operator', ?)")
        .bind(id, body.displayName?.trim() || id)
        .run();
      return json({ id, qrToken: `audiointerview://login?id=${encodeURIComponent(id)}` }, { status: 201 });
    }
  }

  if (request.method === 'GET' && path === '/api/admin/histories') {
    await requireAdmin(request, env);
    const { results } = await env.RI_db.prepare(
      `SELECT interview_sessions.*, accounts.display_name,
       (SELECT COUNT(*) FROM messages WHERE messages.session_id = interview_sessions.id) AS message_count
       FROM interview_sessions JOIN accounts ON accounts.id = interview_sessions.account_id
       ORDER BY interview_sessions.updated_at DESC`,
    ).all();
    return json({ histories: results });
  }

  return error('Not found', 404);
}

export default {
  async fetch(request, env) {
    try {
      return await handleApi(request, env as RuntimeEnv);
    } catch (caught) {
      if (caught instanceof HttpError) return error(caught.message, caught.status);
      if (caught instanceof Error && /UNIQUE constraint/.test(caught.message)) return error('That ID already exists', 409);
      console.error(caught);
      return error(caught instanceof Error ? caught.message : 'Unexpected error', 500);
    }
  },
} satisfies ExportedHandler<Env>;
