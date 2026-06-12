import { redirect } from 'next/navigation'

import { AppHeader } from '../_components/app-header'
import { ConsentClient } from '../_components/consent-client'
import { backendRequest, getCurrentUser } from '../api/_lib/auth'

export default async function ConsentPage() {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    redirect('/login')
  }
  const result = await backendRequest('/internal/account/consents', {
    method: 'GET',
    sessionToken: current.sessionToken,
  })
  if (result.ok && result.data?.complete) {
    redirect('/chat')
  }
  const policyVersion =
    typeof result.data?.current_policy_version === 'string'
      ? result.data.current_policy_version
      : '2026-06-12.1'
  return (
    <main className="min-h-screen bg-zinc-50">
      <AppHeader user={current.user} />
      <ConsentClient policyVersion={policyVersion} />
    </main>
  )
}
