import { redirect } from 'next/navigation'

import { AppHeader } from '../_components/app-header'
import { AssessmentClient } from '../_components/assessment-client'
import { getCurrentUser } from '../api/_lib/auth'
import { requestScreeningBootstrap } from '../api/_lib/screening'

export default async function AssessmentPage() {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    redirect('/login')
  }

  const bootstrap = await requestScreeningBootstrap(current.user.user_id, current.sessionToken)

  return (
    <main className="min-h-screen bg-zinc-50">
      <AppHeader user={current.user} />
      <AssessmentClient initialData={bootstrap.ok ? bootstrap.data : null} />
    </main>
  )
}
