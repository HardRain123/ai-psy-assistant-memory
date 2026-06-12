import { redirect } from 'next/navigation'

import { AppHeader } from '../_components/app-header'
import { AssessmentClient } from '../_components/assessment-client'
import { backendRequest, getCurrentUser } from '../api/_lib/auth'
import { requestScreeningBootstrap } from '../api/_lib/screening'

export default async function AssessmentPage() {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    redirect('/login')
  }
  const consentStatus = await backendRequest('/internal/account/consents', {
    method: 'GET',
    sessionToken: current.sessionToken,
  })
  if (!current.user.is_admin && (!consentStatus.ok || !consentStatus.data?.complete)) {
    redirect('/consent')
  }

  const bootstrap = await requestScreeningBootstrap(current.user.user_id, current.sessionToken)

  return (
    <main className="min-h-screen bg-zinc-50">
      <AppHeader user={current.user} />
      <AssessmentClient initialData={bootstrap.ok ? bootstrap.data : null} />
    </main>
  )
}
