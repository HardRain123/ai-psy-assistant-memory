import { redirect } from 'next/navigation'

import { AdminSafetyDetailClient } from '../../../_components/admin-safety-detail-client'
import { AppHeader } from '../../../_components/app-header'
import { backendRequest, getCurrentUser } from '../../../api/_lib/auth'

export default async function AdminSafetyDetailPage({
  params,
}: {
  params: Promise<{ incidentId: string }>
}) {
  const current = await getCurrentUser()
  if (!current.authenticated) redirect('/login')
  if (!current.user.is_admin) redirect('/chat')
  const { incidentId } = await params
  const result = await backendRequest(
    `/internal/admin/safety/incidents/${encodeURIComponent(incidentId)}`,
    { method: 'GET', sessionToken: current.sessionToken }
  )
  if (!result.ok || !result.data?.incident) redirect('/admin/safety')
  return (
    <main className="min-h-screen bg-zinc-50">
      <AppHeader user={current.user} />
      <AdminSafetyDetailClient initialIncident={result.data.incident} />
    </main>
  )
}
