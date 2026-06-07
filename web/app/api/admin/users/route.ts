import { backendRequest, getCurrentUser } from '../../_lib/auth'

function adminError(status: number, fallback: string) {
  if (status === 401) return '请先登录。'
  if (status === 403) return '没有管理员权限。'
  return fallback
}

export async function GET(req: Request) {
  const current = await getCurrentUser({ refreshSession: true })
  if (!current.authenticated) {
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }
  if (!current.user.is_admin) {
    return Response.json({ error: '没有管理员权限。' }, { status: 403 })
  }

  const { searchParams } = new URL(req.url)
  const q = searchParams.get('q') || ''
  const path = q
    ? `/internal/admin/users?q=${encodeURIComponent(q)}`
    : '/internal/admin/users'
  const result = await backendRequest(path, {
    method: 'GET',
    sessionToken: current.sessionToken,
  })

  if (!result.ok) {
    return Response.json(
      { error: adminError(result.status, '无法读取用户列表，请稍后再试。') },
      { status: result.status }
    )
  }

  return Response.json(result.data, { status: result.status })
}
