'use client'

import { FormEvent, useState } from 'react'

const REQUEST_MESSAGE = '如果邮箱存在，重置链接会发送到该邮箱。'

export function ForgotPasswordForm() {
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (loading) return
    setMessage('')
    setError('')

    if (!email.trim()) {
      setError('请输入邮箱地址。')
      return
    }

    setLoading(true)
    try {
      await fetch('/api/auth/password-reset/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
      })
      setMessage(REQUEST_MESSAGE)
    } catch {
      setMessage(REQUEST_MESSAGE)
    } finally {
      setLoading(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <label className="block text-sm font-medium text-zinc-700">
        邮箱
        <input
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          type="email"
          className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2 outline-none focus:ring-2 focus:ring-zinc-300"
          autoComplete="email"
          required
        />
      </label>

      {error && (
        <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {message && (
        <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {message}
        </p>
      )}

      <button
        type="submit"
        disabled={loading || !email.trim()}
        className="w-full rounded-lg bg-zinc-900 py-3 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
      >
        {loading ? '提交中...' : '发送重置链接'}
      </button>
    </form>
  )
}
