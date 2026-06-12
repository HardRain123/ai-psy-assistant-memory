import { redirect } from 'next/navigation'

import { AccountSettingsClient } from '../../_components/account-settings-client'
import { AccountRightsClient } from '../../_components/account-rights-client'
import { AppHeader } from '../../_components/app-header'
import { getCurrentUser } from '../../api/_lib/auth'

export default async function AccountSettingsPage() {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    redirect('/login')
  }

  return (
    <main className="min-h-screen bg-zinc-50">
      <AppHeader user={current.user} />
      <AccountSettingsClient />
      <AccountRightsClient />
    </main>
  )
}
