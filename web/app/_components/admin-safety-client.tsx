'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

type Incident = {
  incident_id: string
  final_risk_level: string
  immediate_action_required: boolean
  status: string
  source: string
  alert_status: string
  assigned_to_user_id?: string | null
  acknowledged_at?: string | null
  first_response_at?: string | null
  acknowledgement_due_at?: string | null
  first_response_due_at?: string | null
  review_due_at?: string | null
  created_at: string
}

type Overview = {
  coverage_active?: boolean
  coverage_notice?: string
  launch_status?: {
    paused?: boolean
    reason?: string
    active_adult_users?: number
    beta_user_limit?: number
    at_user_limit?: boolean
  }
}

function elapsedMinutes(value: string) {
  const timestamp = new Date(value).getTime()
  return Number.isFinite(timestamp) ? Math.max(0, Math.floor((Date.now() - timestamp) / 60000)) : 0
}

function slaText(item: Incident) {
  const age = elapsedMinutes(item.created_at)
  if (item.final_risk_level === 'medium') {
    const overdue = item.review_due_at && Date.now() > new Date(item.review_due_at).getTime()
    return item.status === 'open' && overdue ? `复核已超时` : `30 分钟内复核，已 ${age} 分钟`
  }
  if (item.final_risk_level === 'high') {
    if (!item.acknowledged_at && item.acknowledgement_due_at && Date.now() > new Date(item.acknowledgement_due_at).getTime()) return '确认已超时'
    if (!item.first_response_at && item.first_response_due_at && Date.now() > new Date(item.first_response_due_at).getTime()) return '首次响应已超时'
    return `确认 5 分钟 / 首响 15 分钟，已 ${age} 分钟`
  }
  return ''
}

export function AdminSafetyClient() {
  const [incidents, setIncidents] = useState<Incident[]>([])
  const [overview, setOverview] = useState<Overview>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [pauseNote, setPauseNote] = useState('')
  const [updatingPause, setUpdatingPause] = useState(false)

  async function load() {
    const response = await fetch('/api/admin/safety')
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      setError(data.error || '安全队列读取失败。')
      setLoading(false)
      return
    }
    setIncidents(data.incidents || [])
    setOverview(data.overview || {})
    setLoading(false)
  }

  async function updatePause(paused: boolean) {
    if (updatingPause || pauseNote.trim().length < 8) return
    setUpdatingPause(true)
    const response = await fetch('/api/admin/safety/invite-pause', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paused, note: pauseNote.trim() }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) setError(data.error || '更新上线闸门失败。')
    else {
      setPauseNote('')
      await load()
    }
    setUpdatingPause(false)
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [])

  const inviteStatus = overview.launch_status?.paused
    ? '已暂停'
    : overview.launch_status?.at_user_limit
      ? '已达上限'
      : '可发放'
  const inviteBlocked = Boolean(
    overview.launch_status?.paused || overview.launch_status?.at_user_limit
  )
  const launchReason = overview.launch_status?.reason

  return (
    <section className="mx-auto max-w-6xl space-y-4 px-4 py-5">
      <div className="rounded-lg border border-zinc-200 bg-white p-5">
        <h1 className="text-lg font-semibold text-zinc-900">心理安全运营台</h1>
        <p className="mt-2 text-sm text-zinc-600">{overview.coverage_notice || '读取值守状态中...'}</p>
        <div className="mt-4 flex flex-wrap gap-2 text-sm">
          <span className={overview.coverage_active ? 'rounded bg-emerald-50 px-2 py-1 text-emerald-800' : 'rounded bg-amber-50 px-2 py-1 text-amber-900'}>
            {overview.coverage_active ? '当前在值守时段' : '当前非值守时段'}
          </span>
          <span className={inviteBlocked ? 'rounded bg-red-50 px-2 py-1 text-red-800' : 'rounded bg-zinc-100 px-2 py-1 text-zinc-700'}>
            邀请码：{inviteStatus}
          </span>
          <span className="rounded bg-zinc-100 px-2 py-1 text-zinc-700">
            成人用户 {overview.launch_status?.active_adult_users || 0}/{overview.launch_status?.beta_user_limit || 50}
          </span>
        </div>
        {launchReason && (
          <p className={`mt-3 rounded-lg p-3 text-sm ${inviteBlocked ? 'bg-red-50 text-red-800' : 'bg-zinc-50 text-zinc-700'}`}>
            {inviteBlocked ? '闸门原因：' : '最近操作：'}{launchReason}
          </p>
        )}
        {overview.launch_status?.at_user_limit && (
          <p className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
            已达到首批成人用户上限，系统会拒绝创建新邀请码。
          </p>
        )}
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <input
            value={pauseNote}
            onChange={(event) => setPauseNote(event.target.value)}
            placeholder="填写暂停或恢复原因，至少 8 个字符"
            className="flex-1 rounded-lg border border-zinc-300 px-3 py-2 text-sm"
          />
          <button onClick={() => updatePause(true)} disabled={updatingPause || pauseNote.trim().length < 8} className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700 disabled:opacity-40">
            暂停邀请
          </button>
          <button onClick={() => updatePause(false)} disabled={updatingPause || pauseNote.trim().length < 8} className="rounded-lg border border-zinc-300 px-3 py-2 text-sm text-zinc-800 disabled:opacity-40">
            恢复邀请
          </button>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white">
        {loading ? (
          <p className="p-5 text-sm text-zinc-500">正在读取队列...</p>
        ) : error ? (
          <p className="p-5 text-sm text-red-700">{error}</p>
        ) : incidents.length === 0 ? (
          <p className="p-5 text-sm text-zinc-500">当前没有中高风险工单。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="bg-zinc-50 text-zinc-500">
                <tr>
                  <th className="px-4 py-3">优先级</th><th className="px-4 py-3">状态</th>
                  <th className="px-4 py-3">来源</th><th className="px-4 py-3">告警</th>
                  <th className="px-4 py-3">时限</th><th className="px-4 py-3">创建时间</th>
                </tr>
              </thead>
              <tbody>
                {incidents.map((item) => (
                  <tr key={item.incident_id} className="border-t border-zinc-100">
                    <td className="px-4 py-3">
                      <Link href={`/admin/safety/${item.incident_id}`} className="font-medium text-zinc-900 underline">
                        {item.immediate_action_required ? '最高优先级' : item.final_risk_level}
                      </Link>
                    </td>
                    <td className="px-4 py-3">{item.status}</td>
                    <td className="px-4 py-3">{item.source}</td>
                    <td className="px-4 py-3">{item.alert_status}</td>
                    <td className="px-4 py-3">{slaText(item)}</td>
                    <td className="px-4 py-3">{new Date(item.created_at).toLocaleString('zh-CN', { hour12: false })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
