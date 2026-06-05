import { redirect } from 'next/navigation'

import { getCurrentUser } from './api/_lib/auth'

export default async function HomePage() {
  const current = await getCurrentUser()
  redirect(current.authenticated ? '/chat' : '/login')
}
