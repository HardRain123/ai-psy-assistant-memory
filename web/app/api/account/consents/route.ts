import { backendRequest, getCurrentUser } from '../../_lib/auth'

export async function GET() {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    return Response.json({ error: 'unauthorized' }, { status: 401 })
  }
  const result = await backendRequest('/internal/account/consents', {
    method: 'GET',
    sessionToken: current.sessionToken,
  })
  return Response.json(result.data, { status: result.status })
}

export async function POST(req: Request) {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    return Response.json({ error: 'unauthorized' }, { status: 401 })
  }
  const body = await req.json().catch(() => ({}))
  const result = await backendRequest('/internal/account/consents', {
    method: 'POST',
    sessionToken: current.sessionToken,
    body: JSON.stringify(body),
  })
  return Response.json(result.data, { status: result.status })
}
