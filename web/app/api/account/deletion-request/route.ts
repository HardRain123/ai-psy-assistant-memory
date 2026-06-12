import { cookies } from 'next/headers'

import { backendRequest, clearSessionCookie, getCurrentUser } from '../../_lib/auth'
import { DELETION_REQUEST_COOKIE, DELETION_TOKEN_COOKIE } from '../_lib/deletion'

function cookieSecure() {
  return process.env.NODE_ENV === 'production'
}

export async function POST(req: Request) {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    return Response.json({ error: 'unauthorized' }, { status: 401 })
  }
  const body = await req.json().catch(() => ({}))
  const result = await backendRequest('/internal/account/deletion-request', {
    method: 'POST',
    sessionToken: current.sessionToken,
    body: JSON.stringify(body),
  })
  if (!result.ok) {
    return Response.json(result.data, { status: result.status })
  }
  const cookieStore = await cookies()
  const cookieOptions = {
    httpOnly: true,
    sameSite: 'lax' as const,
    secure: cookieSecure(),
    path: '/',
    maxAge: 31 * 24 * 60 * 60,
  }
  cookieStore.set(DELETION_REQUEST_COOKIE, result.data.request_id, cookieOptions)
  cookieStore.set(DELETION_TOKEN_COOKIE, result.data.cancellation_token, cookieOptions)
  await clearSessionCookie()
  return Response.json({
    request_id: result.data.request_id,
    status: result.data.status,
    scheduled_for: result.data.scheduled_for,
    backup_delete_by: result.data.backup_delete_by,
  })
}
