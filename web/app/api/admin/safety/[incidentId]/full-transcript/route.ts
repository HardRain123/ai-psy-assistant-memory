import { backendRequest, getCurrentUser } from '../../../../_lib/auth'

type RouteContext = { params: Promise<{ incidentId: string }> }

export async function POST(req: Request, context: RouteContext) {
  const current = await getCurrentUser()
  if (!current.authenticated || !current.user.is_admin) {
    return Response.json({ error: 'forbidden' }, { status: 403 })
  }
  const { incidentId } = await context.params
  const body = await req.json().catch(() => ({}))
  const result = await backendRequest(
    `/internal/admin/safety/incidents/${encodeURIComponent(incidentId)}/full-transcript-access`,
    {
      method: 'POST',
      sessionToken: current.sessionToken,
      body: JSON.stringify(body),
    }
  )
  return Response.json(result.data, { status: result.status })
}
