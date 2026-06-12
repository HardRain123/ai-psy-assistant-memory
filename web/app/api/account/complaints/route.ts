import { backendRequest, getCurrentUser } from '../../_lib/auth'

export async function POST(req: Request) {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    return Response.json({ error: 'unauthorized' }, { status: 401 })
  }
  const body = await req.json().catch(() => ({}))
  const result = await backendRequest('/internal/complaints', {
    method: 'POST',
    sessionToken: current.sessionToken,
    body: JSON.stringify(body),
  })
  return Response.json(result.data, { status: result.status })
}
