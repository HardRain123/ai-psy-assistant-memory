import { clearSessionCookie, getCurrentUser } from '../../_lib/auth'

export async function GET() {
  const current = await getCurrentUser({ refreshSession: true })
  if (!current.authenticated) {
    await clearSessionCookie()
    return Response.json({ authenticated: false })
  }

  return Response.json({
    authenticated: true,
    user: current.user,
    expires_at: current.expires_at,
  })
}
