'use client'

import { useRouter } from 'next/navigation'
import { FormEvent, useEffect, useState } from 'react'

import type { Account } from './types'

function formatTime(value?: string | null) {
  if (!value) return '无'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function AccountSettingsClient() {
  const router = useRouter()
  const [account, setAccount] = useState<Account | null>(null)
  const [email, setEmail] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [loading, setLoading] = useState(true)
  const [emailLoading, setEmailLoading] = useState(false)
  const [passwordLoading, setPasswordLoading] = useState(false)
  const [logoutAllLoading, setLogoutAllLoading] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  async function refreshAccount() {
    try {
      const res = await fetch('/api/auth/account')
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        if (res.status === 401) {
          router.replace('/login')
          return
        }
        setError(data.error || '无法读取账号信息，请稍后再试。')
        return
      }
      setAccount(data.account)
      setEmail(data.account?.email || '')
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    }
  }

  async function requestVerification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (emailLoading) return
    setError('')
    setNotice('')

    if (!email.trim()) {
      setError('请输入邮箱地址。')
      return
    }

    setEmailLoading(true)
    try {
      const res = await fetch('/api/auth/email/request-verification', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        if (res.status === 401) {
          router.replace('/login')
          return
        }
        setError(data.error || '邮箱验证服务暂时不可用，请稍后再试。')
        return
      }
      setNotice(data.message || '如果邮箱可用，验证链接会发送到该邮箱。')
      await refreshAccount()
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setEmailLoading(false)
    }
  }

  async function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (passwordLoading) return
    setError('')
    setNotice('')

    if (newPassword.length < 8) {
      setError('密码至少需要 8 个字符。')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致。')
      return
    }

    setPasswordLoading(true)
    try {
      const res = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.error || '修改密码失败，请稍后再试。')
        return
      }
      router.replace('/login')
      router.refresh()
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setPasswordLoading(false)
    }
  }

  async function logoutAll() {
    if (logoutAllLoading) return
    setLogoutAllLoading(true)
    setError('')
    setNotice('')
    try {
      await fetch('/api/auth/logout-all', { method: 'POST' })
      router.replace('/login')
      router.refresh()
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setLogoutAllLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false

    async function loadInitialAccount() {
      try {
        const res = await fetch('/api/auth/account')
        const data = await res.json().catch(() => ({}))
        if (cancelled) return

        if (!res.ok) {
          if (res.status === 401) {
            router.replace('/login')
            return
          }
          setError(data.error || '无法读取账号信息，请稍后再试。')
          return
        }
        setAccount(data.account)
        setEmail(data.account?.email || '')
      } catch {
        if (!cancelled) {
          setError('网络连接不稳定，请稍后再试。')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadInitialAccount()

    return () => {
      cancelled = true
    }
  }, [router])

  if (loading) {
    return (
      <section className="mx-auto max-w-4xl px-4 py-5">
        <div className="rounded-lg border border-zinc-200 bg-white p-5 text-sm text-zinc-500">
          正在加载账号信息...
        </div>
      </section>
    )
  }

  return (
    <section className="mx-auto grid max-w-4xl gap-4 px-4 py-5">
      <div className="rounded-lg border border-zinc-200 bg-white p-5">
        <h1 className="text-lg font-semibold text-zinc-900">账号设置</h1>
        <p className="mt-1 text-sm leading-6 text-zinc-600">
          管理邮箱验证、密码和当前账号的登录会话。
        </p>

        {notice && (
          <p className="mt-4 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            {notice}
          </p>
        )}

        {error && (
          <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
      </div>

      <div className="rounded-lg border border-zinc-200 bg-white p-5">
        <h2 className="text-base font-semibold text-zinc-900">账号信息</h2>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-zinc-500">账号名</dt>
            <dd className="mt-1 font-medium text-zinc-900">{account?.username || '无'}</dd>
          </div>
          <div>
            <dt className="text-zinc-500">邮箱状态</dt>
            <dd className="mt-1 font-medium text-zinc-900">
              {!account?.has_email ? '未绑定' : account.email_verified ? '已验证' : '待验证'}
            </dd>
          </div>
          <div>
            <dt className="text-zinc-500">当前邮箱</dt>
            <dd className="mt-1 font-medium text-zinc-900">{account?.email || '未绑定'}</dd>
          </div>
          <div>
            <dt className="text-zinc-500">验证时间</dt>
            <dd className="mt-1 font-medium text-zinc-900">{formatTime(account?.email_verified_at)}</dd>
          </div>
        </dl>

        {!account?.has_email && (
          <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
            旧账号还没有绑定邮箱。你仍可正常聊天，但需要绑定并验证邮箱后才能自助找回密码。
          </p>
        )}

        {account?.has_email && !account.email_verified && (
          <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
            当前邮箱尚未验证。请完成验证后再使用邮箱自助找回密码。
          </p>
        )}
      </div>

      <form onSubmit={requestVerification} className="rounded-lg border border-zinc-200 bg-white p-5">
        <h2 className="text-base font-semibold text-zinc-900">绑定或验证邮箱</h2>
        <label className="mt-4 block text-sm font-medium text-zinc-700">
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
        <button
          type="submit"
          disabled={emailLoading || !email.trim()}
          className="mt-4 w-full rounded-lg bg-zinc-900 py-3 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40 sm:w-auto sm:px-4"
        >
          {emailLoading ? '发送中...' : account?.has_email ? '重新发送验证邮件' : '绑定并发送验证邮件'}
        </button>
      </form>

      <form onSubmit={submitPassword} className="rounded-lg border border-zinc-200 bg-white p-5">
        <h2 className="text-base font-semibold text-zinc-900">修改密码</h2>
        <div className="mt-4 grid gap-4">
          <label className="block text-sm font-medium text-zinc-700">
            当前密码
            <input
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              type="password"
              className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2 outline-none focus:ring-2 focus:ring-zinc-300"
              autoComplete="current-password"
              required
            />
          </label>
          <label className="block text-sm font-medium text-zinc-700">
            新密码
            <input
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              type="password"
              className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2 outline-none focus:ring-2 focus:ring-zinc-300"
              autoComplete="new-password"
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
              required
            />
          </label>
        </div>
        <button
          type="submit"
          disabled={passwordLoading || !currentPassword || !newPassword || !confirmPassword}
          className="mt-4 w-full rounded-lg bg-zinc-900 py-3 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40 sm:w-auto sm:px-4"
        >
          {passwordLoading ? '修改中...' : '修改密码'}
        </button>
      </form>

      <div className="rounded-lg border border-zinc-200 bg-white p-5">
        <h2 className="text-base font-semibold text-zinc-900">登录会话</h2>
        <p className="mt-2 text-sm leading-6 text-zinc-600">
          退出全部设备会撤销当前账号的所有登录会话，你需要重新登录。
        </p>
        <button
          onClick={logoutAll}
          disabled={logoutAllLoading}
          className="mt-4 w-full rounded-lg border border-red-200 px-4 py-3 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-40 sm:w-auto"
        >
          {logoutAllLoading ? '退出中...' : '退出全部设备'}
        </button>
      </div>
    </section>
  )
}
