import { backendRequest, getCurrentUser } from '../../_lib/auth'

export async function GET() {
  const current = await getCurrentUser({ refreshSession: true })
  if (!current.authenticated) {
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }

  const result = await backendRequest(`/screening/current/${encodeURIComponent(current.user.user_id)}`, {
    method: 'GET',
    sessionToken: current.sessionToken,
  })

  if (!result.ok) {
    return Response.json(
      { error: '无法读取最近状态评估。' },
      { status: result.status }
    )
  }

  return Response.json(result.data, { status: result.status })
}
