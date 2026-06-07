'use client'

import Link from 'next/link'
import { FormEvent, useState } from 'react'

const INVALID_TOKEN_MESSAGE = '重置链接无效或已过期，请重新申请。'

export function ResetPasswordForm({ token }: { token: string }) {
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState(token ? '' : INVALID_TOKEN_MESSAGE)
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (loading || success) return
    setError('')

    if (!token) {
      setError(INVALID_TOKEN_MESSAGE)
      return
    }

    if (password.length < 8) {
      setError('密码至少需要 8 个字符。')
      return
    }

    if (password !== confirmPassword) {
      setError('两次输入的密码不一致。')
      return
    }

    setLoading(true)
    try {
      const res = await fetch('/api/auth/password-reset/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      })
      const data = await res.json().catch(() => ({}))

      if (!res.ok) {
        setError(data.error || INVALID_TOKEN_MESSAGE)
        return
      }

      setSuccess(data.message || '密码已重置，请使用新密码重新登录。')
      setPassword('')
      setConfirmPassword('')
    } catch {
      setError('密码重置服务暂时不可用，请稍后再试。')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="space-y-4">
        <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {success}
        </p>
        <Link
          href="/login"
          className="block w-full rounded-lg bg-zinc-900 py-3 text-center text-sm font-medium text-white hover:bg-zinc-800"
        >
          返回登录
        </Link>
      </div>
    )
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <label className="block text-sm font-medium text-zinc-700">
        新密码
        <input
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          type="password"
          className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2 outline-none focus:ring-2 focus:ring-zinc-300"
          autoComplete="new-password"
          disabled={!token}
          required
        />
      </label>

      <label className="block text-sm font-medium text-zinc-700">
        确认新密码
        <input
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.target.value)}
          type="password"
          className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2 outline-none focus:ring-2 focus:ring-zinc-300"
          autoComplete="new-password"
          disabled={!token}
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
        disabled={loading || !token || !password || !confirmPassword}
        className="w-full rounded-lg bg-zinc-900 py-3 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
      >
        {loading ? '提交中...' : '重置密码'}
      </button>
    </form>
  )
}
