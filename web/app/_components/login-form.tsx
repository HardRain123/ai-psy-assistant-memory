'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { FormEvent, useState } from 'react'

function stableAuthError(status: number, fallback: string) {
  if (status === 401 || status === 400) return '账号或密码不正确，请检查后再试。'
  if (status >= 500) return '服务暂时不可用，请稍后再试。'
  return fallback
}

export function LoginForm() {
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (loading) return
    setError('')
    setLoading(true)

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      })
      const data = await res.json().catch(() => ({}))

      if (!res.ok) {
        setError(stableAuthError(res.status, data.error || '登录失败，请稍后再试。'))
        return
      }

      router.replace('/chat')
      router.refresh()
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <label className="block text-sm font-medium text-zinc-700">
        账号
        <input
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2 outline-none focus:ring-2 focus:ring-zinc-300"
          autoComplete="username"
          required
        />
      </label>

      <label className="block text-sm font-medium text-zinc-700">
        密码
        <input
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          type="password"
          className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2 outline-none focus:ring-2 focus:ring-zinc-300"
          autoComplete="current-password"
          required
        />
      </label>

      <Link
        href="/forgot-password"
        className="block text-right text-sm font-medium text-zinc-700 underline-offset-4 hover:underline"
      >
        忘记密码？
      </Link>

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={loading || !username.trim() || !password}
        className="w-full rounded-lg bg-zinc-900 py-3 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
      >
        {loading ? '登录中...' : '登录'}
      </button>
    </form>
  )
}
