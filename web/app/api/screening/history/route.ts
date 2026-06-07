import { backendRequest, getCurrentUser } from '../../_lib/auth'

export async function GET(req: Request) {
  const current = await getCurrentUser({ refreshSession: true })
  if (!current.authenticated) {
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }

  const { searchParams } = new URL(req.url)
  const limit = searchParams.get('limit') || '20'
  const result = await backendRequest(
    `/screening/history/${encodeURIComponent(current.user.user_id)}?limit=${encodeURIComponent(limit)}`,
    {
      method: 'GET',
      sessionToken: current.sessionToken,
    }
  )

  if (!result.ok) {
    return Response.json(
      { error: '无法读取状态评估历史。' },
      { status: result.status }
    )
  }

  return Response.json(result.data, { status: result.status })
}
