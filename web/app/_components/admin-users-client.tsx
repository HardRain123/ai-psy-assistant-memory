'use client'

import { FormEvent, useEffect, useState } from 'react'

import { EmptyState } from './notices'
import type { AdminUser } from './types'

function formatTime(value?: string | null) {
  if (!value) return '无'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function statusLabel(user: AdminUser) {
  if (user.disabled_at || user.status === 'disabled') return '已停用'
  if (user.is_admin || user.status === 'admin') return '管理员'
  return '正常'
}

function statusClass(user: AdminUser) {
  if (user.disabled_at || user.status === 'disabled') {
    return 'border-zinc-200 bg-zinc-100 text-zinc-600'
  }
  if (user.is_admin || user.status === 'admin') {
    return 'border-indigo-200 bg-indigo-50 text-indigo-700'
  }
  return 'border-emerald-200 bg-emerald-50 text-emerald-700'
}

function emailStatusLabel(user: AdminUser) {
  if (!user.has_email) return '未绑定'
  if (user.email_verified) return '已验证'
  return '待验证'
}

function emailStatusClass(user: AdminUser) {
  if (!user.has_email) return 'border-zinc-200 bg-zinc-100 text-zinc-600'
  if (user.email_verified) return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  return 'border-amber-200 bg-amber-50 text-amber-800'
}

type ExportPayload = {
  exported_at?: string
  user?: {
    user_id?: string
    username?: string
  }
}

function safeFilenamePart(value?: string | null) {
  const cleaned = (value || 'unknown')
    .replace(/[^A-Za-z0-9_.-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80)
  return cleaned || 'unknown'
}

function timestampForFilename(value?: string) {
  const date = value ? new Date(value) : new Date()
  const safeDate = Number.isNaN(date.getTime()) ? new Date() : date
  const pad = (part: number) => String(part).padStart(2, '0')
  return [
    safeDate.getFullYear(),
    pad(safeDate.getMonth() + 1),
    pad(safeDate.getDate()),
  ].join('') + '-' + [
    pad(safeDate.getHours()),
    pad(safeDate.getMinutes()),
    pad(safeDate.getSeconds()),
  ].join('')
}

function exportFilename(user: AdminUser, payload: ExportPayload) {
  const username = payload.user?.username || user.username || user.user_id
  const userId = payload.user?.user_id || user.user_id
  return `user-export-${safeFilenamePart(username)}-${safeFilenamePart(userId)}-${timestampForFilename(payload.exported_at)}.json`
}

export function AdminUsersClient() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [exportingId, setExportingId] = useState<string | null>(null)
  const [disablingId, setDisablingId] = useState<string | null>(null)
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  async function loadUsers(nextSearch = search) {
    setError('')
    setLoading(true)
    try {
      const query = nextSearch.trim()
      const res = await fetch(query ? `/api/admin/users?q=${encodeURIComponent(query)}` : '/api/admin/users')
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(res.status === 403 ? '没有管理员权限。' : '无法读取用户列表，请稍后再试。')
        return
      }
      setUsers(data.users || [])
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setLoading(false)
    }
  }

  async function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await loadUsers(search)
  }

  async function exportUser(user: AdminUser) {
    if (exportingId) return
    setError('')
    setNotice('')
    setExportingId(user.user_id)
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(user.user_id)}/export`)
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.error || '导出用户数据失败，请稍后再试。')
        return
      }

      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: 'application/json;charset=utf-8',
      })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      const filename = exportFilename(user, data)
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setNotice(`用户数据导出已开始下载：${filename}`)
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setExportingId(null)
    }
  }

  async function disableUser(user: AdminUser) {
    if (disablingId) return
    setError('')
    setNotice('')
    setDisablingId(user.user_id)
    try {
      const res = await fetch(`/api/admin/users/${encodeURIComponent(user.user_id)}/disable`, {
        method: 'POST',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.error || '停用账号失败，请稍后再试。')
        return
      }
      setConfirmingId(null)
      const revokedSessions = typeof data.revoked_sessions === 'number' ? data.revoked_sessions : 0
      setNotice(`已停用账号 ${user.username || user.user_id}，撤销 ${revokedSessions} 个登录会话。`)
      await loadUsers(search)
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setDisablingId(null)
    }
  }

  useEffect(() => {
    let cancelled = false

    async function loadInitialUsers() {
      try {
        const res = await fetch('/api/admin/users')
        const data = await res.json().catch(() => ({}))
        if (cancelled) return

        if (!res.ok) {
          setError(res.status === 403 ? '没有管理员权限。' : '无法读取用户列表，请稍后再试。')
          return
        }
        setUsers(data.users || [])
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

    void loadInitialUsers()

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="mx-auto max-w-6xl px-4 py-5">
      <div className="rounded-lg border border-zinc-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-zinc-900">用户管理</h1>
            <p className="mt-1 text-sm text-zinc-500">
              支持导出完整 JSON 数据包，停用账号会撤销登录会话但保留用户数据。
            </p>
          </div>
          <button
            onClick={() => loadUsers(search)}
            disabled={loading}
            className="rounded-lg border border-zinc-300 px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-100 disabled:opacity-50"
          >
            {loading ? '加载中...' : '刷新'}
          </button>
        </div>

        <form onSubmit={submitSearch} className="mt-4 flex flex-col gap-3 sm:flex-row">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索账号或用户 ID"
            className="min-w-0 flex-1 rounded-lg border border-zinc-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-zinc-300"
          />
          <button
            type="submit"
            disabled={loading}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50"
          >
            搜索
          </button>
        </form>

        {notice && (
          <p className="mt-4 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            {notice}
          </p>
        )}

        {error && (
          <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
      </div>

      <div className="mt-4 rounded-lg border border-zinc-200 bg-white p-4">
        {loading ? (
          <p className="text-sm text-zinc-500">正在加载用户列表...</p>
        ) : users.length === 0 ? (
          <EmptyState title="没有匹配用户" body="调整搜索条件后再试一次。" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1120px] border-collapse text-left text-sm">
              <thead className="border-b border-zinc-200 text-zinc-500">
                <tr>
                  <th className="py-3 pr-4 font-medium">账号</th>
                  <th className="py-3 pr-4 font-medium">邮箱</th>
                  <th className="py-3 pr-4 font-medium">邮箱验证</th>
                  <th className="py-3 pr-4 font-medium">状态</th>
                  <th className="py-3 pr-4 font-medium">会话</th>
                  <th className="py-3 pr-4 font-medium">消息</th>
                  <th className="py-3 pr-4 font-medium">记忆</th>
                  <th className="py-3 pr-4 font-medium">最近登录</th>
                  <th className="py-3 pr-4 font-medium">创建时间</th>
                  <th className="py-3 pr-4 font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {users.map((user) => {
                  const disabled = Boolean(user.disabled_at || user.status === 'disabled')
                  const canDisable = !disabled && !user.is_admin
                  const confirming = confirmingId === user.user_id

                  return (
                    <tr key={user.user_id}>
                      <td className="py-3 pr-4">
                        <p className="font-medium text-zinc-900">{user.username || user.user_id}</p>
                        <p className="mt-1 max-w-[260px] truncate text-xs text-zinc-500">{user.user_id}</p>
                      </td>
                      <td className="py-3 pr-4 text-zinc-700">
                        {user.email_masked || '未绑定'}
                      </td>
                      <td className="py-3 pr-4">
                        <span className={`inline-flex rounded-full border px-2 py-1 text-xs ${emailStatusClass(user)}`}>
                          {emailStatusLabel(user)}
                        </span>
                      </td>
                      <td className="py-3 pr-4">
                        <span className={`inline-flex rounded-full border px-2 py-1 text-xs ${statusClass(user)}`}>
                          {statusLabel(user)}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-zinc-700">{user.counts?.sessions || 0}</td>
                      <td className="py-3 pr-4 text-zinc-700">{user.counts?.messages || 0}</td>
                      <td className="py-3 pr-4 text-zinc-700">{user.counts?.memories || 0}</td>
                      <td className="py-3 pr-4 text-zinc-600">{formatTime(user.last_login_at)}</td>
                      <td className="py-3 pr-4 text-zinc-600">{formatTime(user.created_at)}</td>
                      <td className="py-3 pr-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <button
                            onClick={() => exportUser(user)}
                            disabled={exportingId === user.user_id}
                            className="rounded-lg border border-zinc-300 px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-100 disabled:opacity-50"
                          >
                            {exportingId === user.user_id ? '导出中...' : '导出 JSON'}
                          </button>

                          {canDisable && !confirming && (
                            <button
                              onClick={() => setConfirmingId(user.user_id)}
                              className="rounded-lg border border-red-200 px-3 py-2 text-sm text-red-600 hover:bg-red-50"
                            >
                              停用账号
                            </button>
                          )}

                          {confirming && (
                            <>
                              <button
                                onClick={() => disableUser(user)}
                                disabled={disablingId === user.user_id}
                                className="rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                              >
                                {disablingId === user.user_id ? '停用中...' : '确认停用'}
                              </button>
                              <button
                                onClick={() => setConfirmingId(null)}
                                className="rounded-lg border border-zinc-300 px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-100"
                              >
                                取消
                              </button>
                            </>
                          )}

                          {!canDisable && (
                            <span className="text-xs text-zinc-400">
                              {disabled ? '已停用' : '不可停用'}
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
