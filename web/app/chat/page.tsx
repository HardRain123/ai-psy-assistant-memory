import { redirect } from 'next/navigation'

import { AppHeader } from '../_components/app-header'
import { ChatClient } from '../_components/chat-client'
import { getCurrentUser } from '../api/_lib/auth'

export default async function ChatPage() {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    redirect('/login')
  }

  return (
    <main className="min-h-screen bg-zinc-50">
      <AppHeader user={current.user} />
      <ChatClient user={current.user} />
    </main>
  )
}
