'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

type DeletionStatus = {
  request_id?: string
  status?: string
  requested_at?: string
  scheduled_for?: string
  completed_at?: string
  backup_delete_by?: string
  backup_status?: string
  certificate_id?: string
}

function formatTime(value?: string) {
  if (!value) return '无'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export function AccountDeletionClient() {
  const router = useRouter()
  const [status, setStatus] = useState<DeletionStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [cancelling, setCancelling] = useState(false)
  const [error, setError] = useState('')

  async function loadStatus() {
    const response = await fetch('/api/account/deletion-status')
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      setError('没有找到可查询的删除申请。')
      setLoading(false)
      return
    }
    setStatus(data)
    setLoading(false)
  }

  async function cancelDeletion() {
    if (cancelling) return
    setCancelling(true)
    setError('')
    const response = await fetch('/api/account/deletion-cancel', { method: 'POST' })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      setError(data.error || '撤回失败，请稍后再试。')
      setCancelling(false)
      return
    }
    router.replace('/login')
    router.refresh()
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadStatus()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [])

  return (
    <main className="min-h-screen bg-zinc-50 px-4 py-12">
      <section className="mx-auto max-w-xl rounded-lg border border-zinc-200 bg-white p-6">
        <h1 className="text-xl font-semibold text-zinc-900">账号删除状态</h1>
        {loading ? (
          <p className="mt-4 text-sm text-zinc-600">正在读取状态...</p>
        ) : error ? (
          <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>
        ) : (
          <>
            <dl className="mt-5 grid gap-3 text-sm">
              <div><dt className="text-zinc-500">状态</dt><dd className="font-medium text-zinc-900">{status?.status}</dd></div>
              <div><dt className="text-zinc-500">计划删除时间</dt><dd>{formatTime(status?.scheduled_for)}</dd></div>
              <div><dt className="text-zinc-500">备份最晚删除时间</dt><dd>{formatTime(status?.backup_delete_by)}</dd></div>
              {status?.completed_at && <div><dt className="text-zinc-500">完成时间</dt><dd>{formatTime(status.completed_at)}</dd></div>}
              {status?.certificate_id && <div><dt className="text-zinc-500">删除证书编号</dt><dd className="break-all">{status.certificate_id}</dd></div>}
            </dl>
            {status?.status === 'pending' && (
              <button
                type="button"
                onClick={cancelDeletion}
                disabled={cancelling}
                className="mt-6 rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-800 disabled:opacity-40"
              >
                {cancelling ? '撤回中...' : '撤回删除申请'}
              </button>
            )}
          </>
        )}
        <p className="mt-6 text-xs leading-5 text-zinc-500">
          撤回后需要重新登录。删除完成后，备份副本仍按删除清单在最晚截止日前清除。
        </p>
      </section>
    </main>
  )
}
