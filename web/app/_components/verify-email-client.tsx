'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

const INVALID_TOKEN_MESSAGE = '验证链接无效或已过期，请重新申请。'

export function VerifyEmailClient({ token }: { token: string }) {
  const [loading, setLoading] = useState(Boolean(token))
  const [success, setSuccess] = useState('')
  const [error, setError] = useState(token ? '' : INVALID_TOKEN_MESSAGE)

  useEffect(() => {
    let cancelled = false

    async function confirmEmail() {
      if (!token) return
      setLoading(true)
      setError('')
      setSuccess('')

      try {
        const res = await fetch('/api/auth/email/confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        })
        const data = await res.json().catch(() => ({}))
        if (cancelled) return

        if (!res.ok) {
          setError(data.error || INVALID_TOKEN_MESSAGE)
          return
        }

        setSuccess(data.message || '邮箱已验证。')
      } catch {
        if (!cancelled) {
          setError('邮箱验证服务暂时不可用，请稍后再试。')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void confirmEmail()

    return () => {
      cancelled = true
    }
  }, [token])

  return (
    <div className="space-y-4">
      {loading && (
        <p className="rounded-lg bg-zinc-50 px-3 py-2 text-sm text-zinc-600">
          正在验证邮箱...
        </p>
      )}

      {success && (
        <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {success}
        </p>
      )}

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <Link
          href="/settings/account"
          className="rounded-lg bg-zinc-900 py-3 text-center text-sm font-medium text-white hover:bg-zinc-800"
        >
          查看账号设置
        </Link>
        <Link
          href="/chat"
          className="rounded-lg border border-zinc-300 py-3 text-center text-sm font-medium text-zinc-700 hover:bg-zinc-100"
        >
          返回聊天页
        </Link>
      </div>
    </div>
  )
}
