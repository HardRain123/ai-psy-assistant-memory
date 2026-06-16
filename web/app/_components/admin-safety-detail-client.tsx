'use client'

import { useState } from 'react'

type Message = { message_id: number; role: string; content: string; created_at: string }
type ScreeningSummary = {
  screening_id?: number | null
  instrument?: string
  title?: string
  score?: number
  severity?: string
  label?: string
  risk_level?: string
  risk_flags?: string[]
}
type ScreeningEvidence = {
  trigger_summary?: string[]
  screening_summaries?: ScreeningSummary[]
  stage?: string
  current_danger?: string
  safety_level?: string
  risk_flags?: string[]
  safety_domain?: Record<string, string | number | boolean | null | undefined>
}
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
  source_evidence?: Record<string, unknown>
  alert_status: string
  alert_attempt_count?: number
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

const STAGE_LABELS: Record<string, string> = {
  stable: '稳定',
  mild: '轻度关注',
  moderate: '中度关注',
  high_attention: '高关注',
  urgent_attention: '紧急关注',
}

const SAFETY_FIELD_LABELS: Record<string, string> = {
  supplement_completed: '安全补充模块',
  current_thought: '当前/今日想法',
  plan: '计划',
  means: '工具/条件',
  support: '支持与安全承诺',
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function latestEvidence(incident: Incident): ScreeningEvidence | null {
  const evidence = incident.source_evidence
  if (!isObject(evidence)) return null
  if (Array.isArray(evidence.trigger_summary) || Array.isArray(evidence.screening_summaries)) {
    return evidence as ScreeningEvidence
  }

  const sourceEvidence = evidence[incident.source] || evidence.screening
  if (Array.isArray(sourceEvidence)) {
    const latest = [...sourceEvidence].reverse().find(isObject)
    return latest ? (latest as ScreeningEvidence) : null
  }
  return isObject(sourceEvidence) ? (sourceEvidence as ScreeningEvidence) : null
}

function labelCode(value?: string) {
  if (!value) return ''
  return STAGE_LABELS[value] || value
}

function displayValue(value: string | number | boolean | null | undefined) {
  if (value === true) return '已完成'
  if (value === false) return '未完成'
  if (value === null || value === undefined || value === '') return '未记录'
  return String(value)
}

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
  const evidence = latestEvidence(incident)
  const safetyRows = evidence?.safety_domain
    ? Object.entries(evidence.safety_domain).filter(([, value]) => value !== null && value !== undefined && value !== '')
    : []

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
          {evidence && (
            <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
              <h2 className="font-semibold">触发说明</h2>
              {(evidence.trigger_summary || []).length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {(evidence.trigger_summary || []).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
              <dl className="mt-3 grid gap-2 sm:grid-cols-3">
                {evidence.stage && <div><dt className="text-amber-800">风险阶段</dt><dd>{labelCode(evidence.stage)}</dd></div>}
                {evidence.current_danger && <div><dt className="text-amber-800">当前危险</dt><dd>{labelCode(evidence.current_danger)}</dd></div>}
                {evidence.safety_level && <div><dt className="text-amber-800">安全等级</dt><dd>{evidence.safety_level}</dd></div>}
              </dl>
              {(evidence.screening_summaries || []).length > 0 && (
                <div className="mt-3 space-y-2">
                  {(evidence.screening_summaries || []).map((item, index) => (
                    <div key={`${item.instrument || 'screening'}-${item.screening_id || index}`} className="rounded bg-white/70 p-2">
                      <p className="font-medium">{item.title || item.instrument || '状态评估'}</p>
                      <p className="mt-1 text-amber-900">
                        分数 {displayValue(item.score)}，等级 {displayValue(item.severity)}，风险 {displayValue(item.risk_level)}
                      </p>
                      {item.label && <p className="mt-1 text-amber-900">{item.label}</p>}
                    </div>
                  ))}
                </div>
              )}
              {safetyRows.length > 0 && (
                <dl className="mt-3 grid gap-2 sm:grid-cols-2">
                  {safetyRows.map(([key, value]) => (
                    <div key={key}>
                      <dt className="text-amber-800">{SAFETY_FIELD_LABELS[key] || key}</dt>
                      <dd>{displayValue(value)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          )}
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
            {incident.alert_status === 'failed' && (
              <button
                onClick={() => applyAction('retry_alert')}
                disabled={Boolean(loadingAction)}
                className="col-span-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 disabled:opacity-40"
              >
                {loadingAction === 'retry_alert' ? '正在重新排队...' : '重新发送企业微信告警'}
              </button>
            )}
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
