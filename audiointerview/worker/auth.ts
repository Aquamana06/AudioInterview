import { createAuthSession, deleteAuthSession, ensureAdmin, error, getAccount, getSessionAccount, hashPassword, HttpError } from './db.js';
import type { Account, AuthContext, RuntimeEnv } from './types.js';

const cookieName = 'ai_session';

export function authCookie(request: Request, token: string) {
  return `${cookieName}=${token}; HttpOnly; ${secureCookieAttribute(request)}SameSite=Lax; Path=/; Max-Age=${60 * 60 * 24 * 14}`;
}

export function clearAuthCookie(request: Request) {
  return `${cookieName}=; HttpOnly; ${secureCookieAttribute(request)}SameSite=Lax; Path=/; Max-Age=0`;
}

function secureCookieAttribute(request: Request) {
  const url = new URL(request.url);
  const forwardedProto = request.headers.get('x-forwarded-proto');
  return url.protocol === 'https:' || forwardedProto === 'https' ? 'Secure; ' : '';
}

export function readCookie(request: Request, name: string) {
  const cookie = request.headers.get('cookie') ?? '';
  for (const part of cookie.split(';')) {
    const [key, ...value] = part.trim().split('=');
    if (key === name) return value.join('=');
  }
  return null;
}

export async function requireAuth(request: Request, env: RuntimeEnv): Promise<AuthContext> {
  await ensureAdmin(env);
  const bearer = request.headers.get('authorization')?.match(/^Bearer\s+(.+)$/i)?.[1]?.trim();
  const token = bearer || readCookie(request, cookieName);
  if (!token) throw new HttpError('Authentication required', 401);

  const account = await getSessionAccount(env, token);
  if (!account) throw new HttpError('Authentication required', 401);
  return { account, token };
}

export async function requireAdmin(request: Request, env: RuntimeEnv): Promise<AuthContext> {
  const auth = await requireAuth(request, env);
  if (auth.account.role !== 'admin') throw new HttpError('Admin access required', 403);
  return auth;
}

export async function login(env: RuntimeEnv, id: string, password?: string) {
  await ensureAdmin(env);
  const account = await getAccount(env, id.trim());
  if (!account) throw new HttpError('Unknown or inactive account', 401);

  if (account.role === 'admin') {
    if (!password || !account.password_hash || !account.password_salt) {
      throw new HttpError('Admin password is required', 401);
    }
    const hash = await hashPassword(password, account.password_salt);
    if (hash !== account.password_hash) throw new HttpError('Invalid admin password', 401);
  }

  const token = await createAuthSession(env, account.id);
  return { account: publicAccount(account), token };
}

export async function logout(env: RuntimeEnv, token: string | null) {
  if (token) await deleteAuthSession(env, token);
}

export function publicAccount(account: Account) {
  return {
    id: account.id,
    role: account.role,
    displayName: account.display_name,
  };
}

export function authError(errorValue: unknown) {
  if (errorValue instanceof HttpError) return error(errorValue.message, errorValue.status);
  throw errorValue;
}
