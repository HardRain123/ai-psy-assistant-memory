'use client'

import { useState } from 'react'

type Message = { message_id: number; role: string; content: string; created_at: string }
type Incident = {
  incident_id: string
  user_id: string
  session_id: string
  status: string
  source: string
  source_risk_level: string
  final_risk_level: string
  immediate_action_required: boolean
  risk_flags: string[]
  reason: string
  alert_status: string
  assigned_to_user_id?: string | null
  follow_up_at?: string | null
  message_context: Message[]
  events: Array<{ event_type: string; actor_user_id?: string; note?: string; created_at: string }>
}

const ACTIONS = [
  ['acknowledge', '确认'],
  ['assess', '开始评估'],
  ['contact', '已联系'],
  ['escalate', '升级'],
  ['resolve', '解决'],
  ['false_positive', '标记误报'],
] as const

export function AdminSafetyDetailClient({ initialIncident }: { initialIncident: Incident }) {
  const [incident, setIncident] = useState(initialIncident)
  const [note, setNote] = useState('')
  const [followUpAt, setFollowUpAt] = useState('')
  const [loadingAction, setLoadingAction] = useState('')
  const [accessReason, setAccessReason] = useState('')
  const [transcript, setTranscript] = useState<Message[] | null>(null)
  const [error, setError] = useState('')

  async function applyAction(action: string) {
    setLoadingAction(action)
    setError('')
    const response = await fetch(`/api/admin/safety/${incident.incident_id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action,
        note: note.trim(),
        follow_up_at: followUpAt || undefined,
      }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) setError(data.error || '处置更新失败。')
    else {
      setIncident(data.incident)
      setNote('')
    }
    setLoadingAction('')
  }

  async function accessTranscript() {
    if (accessReason.trim().length < 8) return
    const response = await fetch(`/api/admin/safety/${incident.incident_id}/full-transcript`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: accessReason.trim() }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) setError(data.error || '完整对话读取失败。')
    else setTranscript(data.transcript || [])
  }

  const visibleMessages = transcript || incident.message_context || []

  return (
    <section className="mx-auto grid max-w-6xl gap-4 px-4 py-5 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-4">
        <div className="rounded-lg border border-zinc-200 bg-white p-5">
          <h1 className="text-lg font-semibold text-zinc-900">
            {incident.immediate_action_required ? '最高优先级' : incident.final_risk_level}安全工单
          </h1>
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            <div><dt className="text-zinc-500">事件 ID</dt><dd className="break-all">{incident.incident_id}</dd></div>
            <div><dt className="text-zinc-500">状态</dt><dd>{incident.status}</dd></div>
            <div><dt className="text-zinc-500">来源</dt><dd>{incident.source}</dd></div>
            <div><dt className="text-zinc-500">告警状态</dt><dd>{incident.alert_status}</dd></div>
            <div><dt className="text-zinc-500">最终风险</dt><dd>{incident.final_risk_level}</dd></div>
            <div><dt className="text-zinc-500">立即处置</dt><dd>{incident.immediate_action_required ? '是' : '否'}</dd></div>
          </dl>
          <p className="mt-4 rounded-lg bg-zinc-50 p-3 text-sm text-zinc-700">{incident.reason || '无补充原因'}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {(incident.risk_flags || []).map((flag) => <span key={flag} className="rounded bg-zinc-100 px-2 py-1 text-xs text-zinc-700">{flag}</span>)}
          </div>
        </div>

        <div className="rounded-lg border border-zinc-200 bg-white p-5">
          <h2 className="font-semibold text-zinc-900">{transcript ? '完整会话' : '默认触发上下文'}</h2>
          <div className="mt-4 space-y-3">
            {visibleMessages.map((message) => (
              <div key={message.message_id} className="rounded-lg bg-zinc-50 p-3 text-sm">
                <p className="text-xs text-zinc-500">{message.role} · {message.created_at}</p>
                <p className="mt-1 whitespace-pre-wrap leading-6 text-zinc-900">{message.content}</p>
              </div>
            ))}
          </div>
          {!transcript && (
            <div className="mt-4 border-t border-zinc-200 pt-4">
              <input value={accessReason} onChange={(event) => setAccessReason(event.target.value)} placeholder="填写查看完整会话的业务理由，至少 8 个字符" className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm" />
              <button onClick={accessTranscript} disabled={accessReason.trim().length < 8} className="mt-2 rounded-lg border border-zinc-300 px-3 py-2 text-sm disabled:opacity-40">
                审计并查看完整会话
              </button>
            </div>
          )}
        </div>
      </div>

      <aside className="space-y-4">
        <div className="rounded-lg border border-zinc-200 bg-white p-5">
          <h2 className="font-semibold text-zinc-900">处置操作</h2>
          <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="处置记录" className="mt-3 min-h-24 w-full rounded-lg border border-zinc-300 p-3 text-sm" />
          <label className="mt-3 block text-sm text-zinc-600">
            复查时间
            <input type="datetime-local" value={followUpAt} onChange={(event) => setFollowUpAt(event.target.value)} className="mt-1 w-full rounded-lg border border-zinc-300 px-3 py-2" />
          </label>
          <div className="mt-4 grid grid-cols-2 gap-2">
            {ACTIONS.map(([action, label]) => (
              <button key={action} onClick={() => applyAction(action)} disabled={Boolean(loadingAction)} className="rounded-lg border border-zinc-300 px-3 py-2 text-sm disabled:opacity-40">
                {loadingAction === action ? '处理中...' : label}
              </button>
            ))}
          </div>
          {error && <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        </div>
        <div className="rounded-lg border border-zinc-200 bg-white p-5">
          <h2 className="font-semibold text-zinc-900">事件时间线</h2>
          <div className="mt-3 space-y-3 text-sm">
            {(incident.events || []).map((event, index) => (
              <div key={`${event.event_type}-${index}`} className="border-l-2 border-zinc-200 pl-3">
                <p className="font-medium text-zinc-800">{event.event_type}</p>
                <p className="text-xs text-zinc-500">{event.created_at}</p>
                {event.note && <p className="mt-1 text-zinc-600">{event.note}</p>}
              </div>
            ))}
          </div>
        </div>
      </aside>
    </section>
  )
}
