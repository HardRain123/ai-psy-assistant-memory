'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import type { User } from './types'

export function AppHeader({ user }: { user: User }) {
  const router = useRouter()
  const [loggingOut, setLoggingOut] = useState(false)

  async function logout() {
    if (loggingOut) return
    setLoggingOut(true)
    await fetch('/api/auth/logout', { method: 'POST' }).catch(() => null)
    router.replace('/login')
    router.refresh()
  }

  return (
    <header className="border-b border-zinc-200 bg-white px-4 py-3">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
        <Link href="/chat" className="min-w-0">
          <p className="text-lg font-semibold text-zinc-900">AI 情绪整理助手</p>
          <p className="mt-1 text-xs text-zinc-500">
            当前账号：{user.username}
            {user.is_admin ? '（管理员）' : ''}
          </p>
        </Link>

        <nav className="flex items-center gap-2">
          <Link
            href="/chat"
            className="rounded-lg px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-100"
          >
            聊天
          </Link>
          {user.is_admin && (
            <Link
              href="/admin/invites"
              className="rounded-lg px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-100"
            >
              邀请码
            </Link>
          )}
          <button
            onClick={logout}
            disabled={loggingOut}
            className="rounded-lg border border-zinc-300 px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-100 disabled:opacity-50"
          >
            {loggingOut ? '退出中...' : '退出登录'}
          </button>
        </nav>
      </div>
    </header>
  )
}
