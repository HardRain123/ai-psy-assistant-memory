import { backendRequest, getCurrentUser } from '../../_lib/auth'

export async function GET() {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    return Response.json({ error: 'unauthorized' }, { status: 401 })
  }
  const result = await backendRequest('/internal/account/export', {
    method: 'GET',
    sessionToken: current.sessionToken,
  })
  if (!result.ok) {
    return Response.json(result.data, { status: result.status })
  }
  return new Response(JSON.stringify(result.data, null, 2), {
    status: 200,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Content-Disposition': `attachment; filename="account-data-${new Date().toISOString().slice(0, 10)}.json"`,
    },
  })
}
