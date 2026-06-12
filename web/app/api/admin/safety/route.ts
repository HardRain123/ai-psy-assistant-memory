import { backendRequest, getCurrentUser } from '../../_lib/auth'

export async function GET() {
  const current = await getCurrentUser()
  if (!current.authenticated || !current.user.is_admin) {
    return Response.json({ error: 'forbidden' }, { status: 403 })
  }
  const [overview, incidents] = await Promise.all([
    backendRequest('/internal/admin/safety/overview', {
      method: 'GET',
      sessionToken: current.sessionToken,
    }),
    backendRequest('/internal/admin/safety/incidents', {
      method: 'GET',
      sessionToken: current.sessionToken,
    }),
  ])
  if (!overview.ok) return Response.json(overview.data, { status: overview.status })
  if (!incidents.ok) return Response.json(incidents.data, { status: incidents.status })
  return Response.json({ overview: overview.data, incidents: incidents.data.incidents || [] })
}
