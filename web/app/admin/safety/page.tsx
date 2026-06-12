import { redirect } from 'next/navigation'

import { AdminSafetyClient } from '../../_components/admin-safety-client'
import { AppHeader } from '../../_components/app-header'
import { getCurrentUser } from '../../api/_lib/auth'

export default async function AdminSafetyPage() {
  const current = await getCurrentUser()
  if (!current.authenticated) redirect('/login')
  if (!current.user.is_admin) redirect('/chat')
  return (
    <main className="min-h-screen bg-zinc-50">
      <AppHeader user={current.user} />
      <AdminSafetyClient />
    </main>
  )
}
