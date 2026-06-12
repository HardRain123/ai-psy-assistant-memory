'use client'

import { useRouter } from 'next/navigation'
import { FormEvent, useState } from 'react'

function stableRegisterError(status: number, fallback: string) {
  if (status === 400) return fallback || '注册信息有误，请检查后再试。'
  if (status === 409) return fallback || '账号或邮箱已经被注册，请换一个再试。'
  if (status === 401 || status === 403) return '邀请码不可用或已失效。'
  if (status >= 500) return '服务暂时不可用，请稍后再试。'
  return fallback || '注册失败，请稍后再试。'
}

export function RegisterForm() {
  const router = useRouter()
  const [inviteCode, setInviteCode] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [consents, setConsents] = useState({
    adultConfirmed: false,
    aiServiceConsent: false,
    sensitiveDataConsent: false,
    conversationStorageConsent: false,
    longTermMemoryConsent: false,
    humanSafetyReviewConsent: false,
  })
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
    if (!email.trim()) {
      setError('请输入邮箱地址。')
      return
    }
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致。')
      return
    }
    if (Object.values(consents).some((value) => !value)) {
      setError('请逐项确认年龄要求和全部必要授权。')
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
          email: email.trim(),
          password,
          policyVersion: '2026-06-12.1',
          ...consents,
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

      <fieldset className="space-y-3 rounded-lg border border-zinc-200 bg-zinc-50 p-4">
        <legend className="px-1 text-sm font-semibold text-zinc-900">年龄与分项授权</legend>
        {[
          ['adultConfirmed', '我确认已年满 18 岁。'],
          ['aiServiceConsent', '我同意使用 AI 服务，并理解它不替代医疗诊断或真人咨询。'],
          ['sensitiveDataConsent', '我同意处理对话中涉及的心理健康敏感信息。'],
          ['conversationStorageConsent', '我同意保存对话，用于本账号的连续服务。'],
          ['longTermMemoryConsent', '我同意生成和保存长期记忆、总结与计划。'],
          ['humanSafetyReviewConsent', '我同意在安全风险触发时由授权人员进行人工复核。'],
        ].map(([key, label]) => (
          <label key={key} className="flex items-start gap-3 text-sm leading-6 text-zinc-700">
            <input
              type="checkbox"
              checked={consents[key as keyof typeof consents]}
              onChange={(event) =>
                setConsents((current) => ({ ...current, [key]: event.target.checked }))
              }
              className="mt-1"
            />
            <span>{label}</span>
          </label>
        ))}
        <p className="text-xs leading-5 text-zinc-500">
          人工安全值守时间为工作日 09:00–18:00（中国时间），不是 7×24 小时危机服务。
          首版不收集手机号或紧急联系人。
        </p>
      </fieldset>

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
        disabled={
          loading ||
          !username.trim() ||
          !email.trim() ||
          !password ||
          !confirmPassword ||
          Object.values(consents).some((value) => !value)
        }
        className="w-full rounded-lg bg-zinc-900 py-3 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
      >
        {loading ? '注册中...' : '注册并进入聊天'}
      </button>
    </form>
  )
}
