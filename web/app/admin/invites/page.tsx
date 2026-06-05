import Link from 'next/link'
import { redirect } from 'next/navigation'

import { AdminInvitesClient } from '../../_components/admin-invites-client'
import { AppHeader } from '../../_components/app-header'
import { getCurrentUser } from '../../api/_lib/auth'

export default async function AdminInvitesPage() {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    redirect('/login')
  }

  if (!current.user.is_admin) {
    return (
      <main className="min-h-screen bg-zinc-50">
        <AppHeader user={current.user} />
        <section className="mx-auto max-w-2xl px-4 py-16">
          <div className="rounded-lg border border-zinc-200 bg-white p-6 text-center">
            <h1 className="text-lg font-semibold text-zinc-900">没有管理员权限</h1>
            <p className="mt-3 text-sm leading-6 text-zinc-600">
              当前账号不能查看或管理邀请码。你仍然可以继续使用聊天页面。
            </p>
            <Link
              href="/chat"
              className="mt-5 inline-flex rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800"
            >
              返回聊天页
            </Link>
          </div>
        </section>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-zinc-50">
      <AppHeader user={current.user} />
      <AdminInvitesClient />
    </main>
  )
}
