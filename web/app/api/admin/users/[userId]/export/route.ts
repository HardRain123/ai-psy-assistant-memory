import { backendRequest, getCurrentUser } from '../../../../_lib/auth'

type RouteContext = {
  params: Promise<{ userId: string }>
}

function adminError(status: number, fallback: string) {
  if (status === 401) return '请先登录。'
  if (status === 403) return '没有管理员权限。'
  if (status === 404) return '用户不存在。'
  return fallback
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

function exportFilename(userId: string, data: Record<string, unknown>) {
  const exportedUser = data.user && typeof data.user === 'object'
    ? data.user as { user_id?: string; username?: string }
    : {}
  const username = exportedUser.username || userId
  const exportedUserId = exportedUser.user_id || userId
  const exportedAt = typeof data.exported_at === 'string' ? data.exported_at : undefined
  return `user-export-${safeFilenamePart(username)}-${safeFilenamePart(exportedUserId)}-${timestampForFilename(exportedAt)}.json`
}

function forwardedHeaders(req: Request) {
  const headers = new Headers()
  const forwardedFor = req.headers.get('x-forwarded-for')
  const userAgent = req.headers.get('user-agent')
  if (forwardedFor) headers.set('X-Forwarded-For', forwardedFor)
  if (userAgent) headers.set('X-Forwarded-User-Agent', userAgent)
  return headers
}

export async function GET(req: Request, context: RouteContext) {
  const current = await getCurrentUser({ refreshSession: true })
  if (!current.authenticated) {
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }
  if (!current.user.is_admin) {
    return Response.json({ error: '没有管理员权限。' }, { status: 403 })
  }

  const { userId } = await context.params
  const result = await backendRequest(`/internal/admin/users/${encodeURIComponent(userId)}/export`, {
    method: 'GET',
    sessionToken: current.sessionToken,
    headers: forwardedHeaders(req),
  })

  if (!result.ok) {
    return Response.json(
      { error: adminError(result.status, '导出用户数据失败，请稍后再试。') },
      { status: result.status }
    )
  }

  return Response.json(result.data, {
    status: result.status,
    headers: {
      'Content-Disposition': `attachment; filename=${exportFilename(userId, result.data || {})}`,
    },
  })
}
