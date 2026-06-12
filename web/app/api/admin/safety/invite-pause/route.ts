import { backendRequest, getCurrentUser } from '../../../_lib/auth'

export async function POST(req: Request) {
  const current = await getCurrentUser()
  if (!current.authenticated || !current.user.is_admin) {
    return Response.json({ error: 'forbidden' }, { status: 403 })
  }
  const body = await req.json().catch(() => ({}))
  const result = await backendRequest('/internal/admin/safety/invite-pause', {
    method: 'POST',
    sessionToken: current.sessionToken,
    body: JSON.stringify(body),
  })
  return Response.json(result.data, { status: result.status })
}
