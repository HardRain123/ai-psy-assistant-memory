import { backendRequest, clearSessionCookie, getSessionToken } from '../../_lib/auth'

export async function POST() {
  const sessionToken = await getSessionToken()
  if (sessionToken) {
    await backendRequest('/internal/auth/logout', {
      method: 'POST',
      sessionToken,
    })
  }

  await clearSessionCookie()
  return Response.json({ success: true })
}
