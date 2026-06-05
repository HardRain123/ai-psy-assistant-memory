import { cookies } from 'next/headers'

export const AUTH_COOKIE = 'psy_auth_session'

type BackendInit = RequestInit & {
  sessionToken?: string
}

function backendBaseUrl() {
  return (
    process.env.FASTAPI_INTERNAL_URL ||
    process.env.BACKEND_API_URL ||
    process.env.BACKEND_URL ||
    'http://127.0.0.1:8000'
  ).replace(/\/$/, '')
}

export function sessionMaxAge() {
  const raw = Number(process.env.SESSION_TTL_DAYS || '7')
  const days = Number.isFinite(raw) && raw > 0 ? raw : 7
  return days * 24 * 60 * 60
}

export async function getSessionToken() {
  const cookieStore = await cookies()
  return cookieStore.get(AUTH_COOKIE)?.value || ''
}

export async function setSessionCookie(sessionToken: string) {
  const cookieStore = await cookies()
  cookieStore.set(AUTH_COOKIE, sessionToken, {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: sessionMaxAge(),
  })
}

export async function clearSessionCookie() {
  const cookieStore = await cookies()
  cookieStore.set(AUTH_COOKIE, '', {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production',
    path: '/',
    maxAge: 0,
  })
}

export async function backendRequest(path: string, init: BackendInit = {}) {
  const { sessionToken, ...fetchInit } = init
  const backendToken = process.env.BACKEND_SHARED_TOKEN
  if (!backendToken) {
    return {
      ok: false,
      status: 500,
      data: { error: 'backend_unavailable' },
    }
  }

  const headers = new Headers(fetchInit.headers)
  headers.set('X-Backend-Token', backendToken)

  if (sessionToken) {
    headers.set('X-Auth-Session', sessionToken)
  }

  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  try {
    const res = await fetch(`${backendBaseUrl()}${path}`, {
      ...fetchInit,
      headers,
      cache: 'no-store',
    })

    const data = await res.json().catch(() => ({}))
    return { ok: res.ok, status: res.status, data }
  } catch {
    return {
      ok: false,
      status: 502,
      data: { error: 'backend_unavailable' },
    }
  }
}

export async function getCurrentUser(options: { refreshSession?: boolean } = {}) {
  const sessionToken = await getSessionToken()
  if (!sessionToken) {
    return { authenticated: false as const, sessionToken: '' }
  }

  const result = await backendRequest('/internal/auth/me', {
    method: 'GET',
    sessionToken,
  })

  if (!result.ok || !result.data?.authenticated) {
    return { authenticated: false as const, sessionToken: '' }
  }

  if (options.refreshSession) {
    await setSessionCookie(sessionToken)
  }

  return {
    authenticated: true as const,
    sessionToken,
    user: result.data.user as {
      user_id: string
      username: string
      is_admin: boolean
    },
    expires_at: result.data.expires_at as string,
  }
}
