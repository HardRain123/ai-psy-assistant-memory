import { backendRequest, getCurrentUser } from '../../../../_lib/auth'

type RouteContext = {
  params: Promise<{ userId: string }>
}

function adminError(status: number) {
  if (status === 401) return '请先登录。'
  if (status === 403) return '没有管理员权限。'
  if (status === 404) return '用户不存在。'
  return '清除对话历史失败，请稍后再试。'
}

function forwardedHeaders(req: Request) {
  const headers = new Headers()
  const forwardedFor = req.headers.get('x-forwarded-for')
  const userAgent = req.headers.get('user-agent')
  if (forwardedFor) headers.set('X-Forwarded-For', forwardedFor)
  if (userAgent) headers.set('X-Forwarded-User-Agent', userAgent)
  return headers
}

export async function DELETE(req: Request, context: RouteContext) {
  const current = await getCurrentUser({ refreshSession: true })
  if (!current.authenticated) {
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }
  if (!current.user.is_admin) {
    return Response.json({ error: '没有管理员权限。' }, { status: 403 })
  }

  const { userId } = await context.params
  const result = await backendRequest(
    `/internal/admin/users/${encodeURIComponent(userId)}/conversation-history`,
    {
      method: 'DELETE',
      sessionToken: current.sessionToken,
      headers: forwardedHeaders(req),
    }
  )

  if (!result.ok) {
    return Response.json(
      { error: adminError(result.status) },
      { status: result.status }
    )
  }

  return Response.json(result.data, { status: result.status })
}
