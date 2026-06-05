'use client'

import { useEffect, useState } from 'react'

import { EmptyState } from './notices'
import type { Invite } from './types'

function statusLabel(invite: Invite) {
  if (invite.revoked_at || invite.status === 'revoked') return '已撤销'
  if (invite.used_at || invite.status === 'used') return '已使用'
  return '未使用'
}

function formatTime(value?: string | null) {
  if (!value) return '无'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function AdminInvitesClient() {
  const [invites, setInvites] = useState<Invite[]>([])
  const [note, setNote] = useState('')
  const [createdCode, setCreatedCode] = useState('')
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [revokingId, setRevokingId] = useState<number | null>(null)
  const [error, setError] = useState('')

  async function loadInvites() {
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/api/admin/invites')
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(res.status === 403 ? '没有管理员权限。' : '无法读取邀请码，请稍后再试。')
        return
      }
      setInvites(data.invites || [])
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setLoading(false)
    }
  }

  async function createInvite() {
    if (creating) return
    setError('')
    setCreatedCode('')
    setCreating(true)
    try {
      const res = await fetch('/api/admin/invites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: note.trim() }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError('创建邀请码失败，请稍后再试。')
        return
      }
      setCreatedCode(data.invite?.code || '')
      setNote('')
      await loadInvites()
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setCreating(false)
    }
  }

  async function revokeInvite(inviteId: number) {
    if (revokingId) return
    setError('')
    setRevokingId(inviteId)
    try {
      const res = await fetch('/api/admin/invites', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invite_id: inviteId }),
      })
      if (!res.ok) {
        setError('撤销邀请码失败，请稍后再试。')
        return
      }
      await loadInvites()
    } catch {
      setError('网络连接不稳定，请稍后再试。')
    } finally {
      setRevokingId(null)
    }
  }

  useEffect(() => {
    let cancelled = false

    async function loadInitialInvites() {
      try {
        const res = await fetch('/api/admin/invites')
        const data = await res.json().catch(() => ({}))
        if (cancelled) return

        if (!res.ok) {
          setError(res.status === 403 ? '没有管理员权限。' : '无法读取邀请码，请稍后再试。')
          return
        }
        setInvites(data.invites || [])
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

    void loadInitialInvites()

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="mx-auto max-w-6xl px-4 py-5">
      <div className="rounded-lg border border-zinc-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-zinc-900">邀请码管理</h1>
            <p className="mt-1 text-sm text-zinc-500">
              原始邀请码只会在创建成功后显示一次，列表不会展示邀请码原文或校验值。
            </p>
          </div>
          <button
            onClick={loadInvites}
            disabled={loading}
            className="rounded-lg border border-zinc-300 px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-100 disabled:opacity-50"
          >
            {loading ? '加载中...' : '刷新'}
          </button>
        </div>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row">
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="备注，可选"
            className="min-w-0 flex-1 rounded-lg border border-zinc-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-zinc-300"
          />
          <button
            onClick={createInvite}
            disabled={creating}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-50"
          >
            {creating ? '生成中...' : '生成邀请码'}
          </button>
        </div>

        {createdCode && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
            <p className="font-medium">新邀请码只显示一次：</p>
            <code className="mt-2 block break-all rounded bg-white px-2 py-1 text-zinc-900">
              {createdCode}
            </code>
          </div>
        )}

        {error && (
          <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
      </div>

      <div className="mt-4 rounded-lg border border-zinc-200 bg-white p-4">
        {loading ? (
          <p className="text-sm text-zinc-500">正在加载邀请码列表...</p>
        ) : invites.length === 0 ? (
          <EmptyState title="还没有邀请码" body="生成一个邀请码后，可以把邀请码原文发给测试用户注册。" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left text-sm">
              <thead className="border-b border-zinc-200 text-zinc-500">
                <tr>
                  <th className="py-3 pr-4 font-medium">ID</th>
                  <th className="py-3 pr-4 font-medium">状态</th>
                  <th className="py-3 pr-4 font-medium">创建时间</th>
                  <th className="py-3 pr-4 font-medium">使用时间</th>
                  <th className="py-3 pr-4 font-medium">备注</th>
                  <th className="py-3 pr-4 font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {invites.map((invite) => {
                  const active = statusLabel(invite) === '未使用'
                  return (
                    <tr key={invite.id}>
                      <td className="py-3 pr-4 text-zinc-900">#{invite.id}</td>
                      <td className="py-3 pr-4 text-zinc-700">{statusLabel(invite)}</td>
                      <td className="py-3 pr-4 text-zinc-600">{formatTime(invite.created_at)}</td>
                      <td className="py-3 pr-4 text-zinc-600">{formatTime(invite.used_at)}</td>
                      <td className="py-3 pr-4 text-zinc-600">{invite.note || '无'}</td>
                      <td className="py-3 pr-4">
                        {active ? (
                          <button
                            onClick={() => revokeInvite(invite.id)}
                            disabled={revokingId === invite.id}
                            className="text-red-600 hover:underline disabled:opacity-50"
                          >
                            {revokingId === invite.id ? '撤销中...' : '撤销'}
                          </button>
                        ) : (
                          <span className="text-zinc-400">不可操作</span>
                        )}
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
