import { backendRequest, getCurrentUser } from '../../../_lib/auth'

type RouteContext = { params: Promise<{ incidentId: string }> }

export async function GET(_req: Request, context: RouteContext) {
  const current = await getCurrentUser()
  if (!current.authenticated || !current.user.is_admin) {
    return Response.json({ error: 'forbidden' }, { status: 403 })
  }
  const { incidentId } = await context.params
  const result = await backendRequest(
    `/internal/admin/safety/incidents/${encodeURIComponent(incidentId)}`,
    { method: 'GET', sessionToken: current.sessionToken }
  )
  return Response.json(result.data, { status: result.status })
}

export async function POST(req: Request, context: RouteContext) {
  const current = await getCurrentUser()
  if (!current.authenticated || !current.user.is_admin) {
    return Response.json({ error: 'forbidden' }, { status: 403 })
  }
  const { incidentId } = await context.params
  const body = await req.json().catch(() => ({}))
  const retryAlert = body.action === 'retry_alert'
  const result = await backendRequest(
    retryAlert
      ? `/internal/admin/safety/incidents/${encodeURIComponent(incidentId)}/alert-retry`
      : `/internal/admin/safety/incidents/${encodeURIComponent(incidentId)}/actions`,
    {
      method: 'POST',
      sessionToken: current.sessionToken,
      body: JSON.stringify(retryAlert ? { note: body.note || '' } : body),
    }
  )
  return Response.json(result.data, { status: result.status })
}
