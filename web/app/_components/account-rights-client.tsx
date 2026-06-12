'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

export function AccountRightsClient() {
  const router = useRouter()
  const [exporting, setExporting] = useState(false)
  const [complaintCategory, setComplaintCategory] = useState('service')
  const [complaint, setComplaint] = useState('')
  const [complaintLoading, setComplaintLoading] = useState(false)
  const [deleteText, setDeleteText] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  async function exportData() {
    if (exporting) return
    setExporting(true)
    setError('')
    try {
      const response = await fetch('/api/account/export')
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        setError(data.error || '数据导出失败，请稍后再试。')
        return
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `account-data-${new Date().toISOString().slice(0, 10)}.json`
      anchor.click()
      URL.revokeObjectURL(url)
      setNotice('数据导出已开始下载。')
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setExporting(false)
    }
  }

  async function submitComplaint() {
    if (complaintLoading || complaint.trim().length < 10) return
    setComplaintLoading(true)
    setError('')
    setNotice('')
    try {
      const response = await fetch('/api/account/complaints', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category: complaintCategory, content: complaint.trim() }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setError(data.error || '投诉提交失败，请稍后再试。')
        return
      }
      setComplaint('')
      setNotice(`投诉已提交，编号：${data.complaint?.complaint_id || '已记录'}`)
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setComplaintLoading(false)
    }
  }

  async function requestDeletion() {
    if (deleting || deleteText !== '删除我的账号') return
    if (!window.confirm('申请后账号会立即冻结并退出全部设备，7 天后永久删除。确认继续吗？')) return
    setDeleting(true)
    setError('')
    try {
      const response = await fetch('/api/account/deletion-request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm_text: deleteText }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setError(data.error || '删除申请失败，请稍后再试。')
        return
      }
      router.replace('/account-deletion')
      router.refresh()
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <section className="mx-auto grid max-w-4xl gap-4 px-4 pb-8">
      {(notice || error) && (
        <div className={error ? 'rounded-lg bg-red-50 p-3 text-sm text-red-700' : 'rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800'}>
          {error || notice}
        </div>
      )}

      <div className="rounded-lg border border-zinc-200 bg-white p-5">
        <h2 className="text-base font-semibold text-zinc-900">导出我的数据</h2>
        <p className="mt-2 text-sm leading-6 text-zinc-600">
          导出账号资料、对话、记忆、评估、授权记录、风险事件和投诉记录，格式为 JSON。
        </p>
        <button
          type="button"
          onClick={exportData}
          disabled={exporting}
          className="mt-4 rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-800 disabled:opacity-40"
        >
          {exporting ? '导出中...' : '下载数据副本'}
        </button>
      </div>

      <div className="rounded-lg border border-zinc-200 bg-white p-5">
        <h2 className="text-base font-semibold text-zinc-900">提交投诉</h2>
        <select
          value={complaintCategory}
          onChange={(event) => setComplaintCategory(event.target.value)}
          className="mt-4 rounded-lg border border-zinc-300 px-3 py-2 text-sm"
        >
          <option value="service">服务问题</option>
          <option value="privacy">隐私与数据</option>
          <option value="safety">安全处置</option>
          <option value="content">内容问题</option>
          <option value="other">其他</option>
        </select>
        <textarea
          value={complaint}
          onChange={(event) => setComplaint(event.target.value)}
          className="mt-3 min-h-28 w-full rounded-lg border border-zinc-300 p-3 text-sm"
          placeholder="请描述问题，至少 10 个字符。"
        />
        <button
          type="button"
          onClick={submitComplaint}
          disabled={complaintLoading || complaint.trim().length < 10}
          className="mt-3 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          {complaintLoading ? '提交中...' : '提交投诉'}
        </button>
      </div>

      <div className="rounded-lg border border-red-200 bg-white p-5">
        <h2 className="text-base font-semibold text-red-800">删除账号与数据</h2>
        <p className="mt-2 text-sm leading-6 text-zinc-600">
          申请后账号立即冻结并撤销全部登录会话，7 天后删除主数据库中的账号数据。
          备份中的副本最长保留 30 天，并进入删除清单。
        </p>
        <label className="mt-4 block text-sm font-medium text-zinc-700">
          输入“删除我的账号”确认
          <input
            value={deleteText}
            onChange={(event) => setDeleteText(event.target.value)}
            className="mt-2 w-full rounded-lg border border-red-200 px-3 py-2"
          />
        </label>
        <button
          type="button"
          onClick={requestDeletion}
          disabled={deleting || deleteText !== '删除我的账号'}
          className="mt-4 rounded-lg bg-red-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          {deleting ? '申请中...' : '申请删除账号'}
        </button>
      </div>
    </section>
  )
}
