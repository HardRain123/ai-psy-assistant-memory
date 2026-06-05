'use client'

import { useRouter } from 'next/navigation'
import { FormEvent, useState } from 'react'

function stableRegisterError(status: number, fallback: string) {
  if (status === 400) return fallback || '注册信息有误，请检查后再试。'
  if (status === 409) return fallback || '这个账号已经被注册，请换一个账号名。'
  if (status === 401 || status === 403) return '邀请码不可用或已失效。'
  if (status >= 500) return '服务暂时不可用，请稍后再试。'
  return fallback || '注册失败，请稍后再试。'
}

export function RegisterForm() {
  const router = useRouter()
  const [inviteCode, setInviteCode] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (loading) return
    setError('')

    if (!inviteCode.trim()) {
      setError('请输入邀请码。')
      return
    }
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致。')
      return
    }

    setLoading(true)
    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          inviteCode: inviteCode.trim(),
          username: username.trim(),
          password,
        }),
      })
      const data = await res.json().catch(() => ({}))

      if (!res.ok) {
        setError(stableRegisterError(res.status, data.error || '注册失败，请稍后再试。'))
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
        邀请码
        <input
          value={inviteCode}
          onChange={(event) => setInviteCode(event.target.value)}
          className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2 outline-none focus:ring-2 focus:ring-zinc-300"
          autoComplete="one-time-code"
          required
        />
      </label>

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
          autoComplete="new-password"
          required
        />
      </label>

      <label className="block text-sm font-medium text-zinc-700">
        确认密码
        <input
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.target.value)}
          type="password"
          className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2 outline-none focus:ring-2 focus:ring-zinc-300"
          autoComplete="new-password"
          required
        />
      </label>

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={loading || !username.trim() || !password || !confirmPassword}
        className="w-full rounded-lg bg-zinc-900 py-3 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
      >
        {loading ? '注册中...' : '注册并进入聊天'}
      </button>
    </form>
  )
}
