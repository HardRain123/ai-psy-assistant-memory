'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

const ITEMS = [
  ['adultConfirmed', '我确认已年满 18 岁。'],
  ['aiServiceConsent', '我同意使用 AI 服务，并理解它不替代医疗诊断或真人咨询。'],
  ['sensitiveDataConsent', '我同意处理对话中涉及的心理健康敏感信息。'],
  ['conversationStorageConsent', '我同意保存对话，用于本账号的连续服务。'],
  ['longTermMemoryConsent', '我同意生成和保存长期记忆、总结与计划。'],
  ['humanSafetyReviewConsent', '我同意在安全风险触发时由授权人员进行人工复核。'],
] as const

export function ConsentClient({ policyVersion }: { policyVersion: string }) {
  const router = useRouter()
  const [values, setValues] = useState<Record<(typeof ITEMS)[number][0], boolean>>({
    adultConfirmed: false,
    aiServiceConsent: false,
    sensitiveDataConsent: false,
    conversationStorageConsent: false,
    longTermMemoryConsent: false,
    humanSafetyReviewConsent: false,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    if (loading || Object.values(values).some((value) => !value)) return
    setLoading(true)
    setError('')
    try {
      const response = await fetch('/api/account/consents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ policyVersion, ...values }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setError(data.error || data.detail || '授权保存失败，请稍后再试。')
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
    <section className="mx-auto max-w-2xl px-4 py-10">
      <div className="rounded-lg border border-zinc-200 bg-white p-6">
        <h1 className="text-xl font-semibold text-zinc-900">完成年龄确认与分项授权</h1>
        <p className="mt-2 text-sm leading-6 text-zinc-600">
          为继续使用聊天和状态评估，请逐项阅读并确认。你可以在账号设置中导出数据、申请删除或投诉。
        </p>
        <div className="mt-6 space-y-3">
          {ITEMS.map(([key, label]) => (
            <label key={key} className="flex items-start gap-3 rounded-lg border border-zinc-200 p-3 text-sm leading-6 text-zinc-700">
              <input
                type="checkbox"
                checked={values[key]}
                onChange={(event) =>
                  setValues((current) => ({ ...current, [key]: event.target.checked }))
                }
                className="mt-1"
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
        <div className="mt-5 rounded-lg bg-amber-50 p-3 text-sm leading-6 text-amber-950">
          人工安全值守时间为工作日 09:00–18:00（中国时间），不是 7×24 小时危机服务。
          紧急危险请拨打 110 或 120。首版不收集手机号或紧急联系人。
        </div>
        {error && <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        <button
          type="button"
          onClick={submit}
          disabled={loading || Object.values(values).some((value) => !value)}
          className="mt-6 w-full rounded-lg bg-zinc-900 px-4 py-3 text-sm font-medium text-white disabled:opacity-40"
        >
          {loading ? '保存中...' : '确认并继续'}
        </button>
      </div>
    </section>
  )
}
