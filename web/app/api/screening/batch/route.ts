import { backendRequest, getCurrentUser } from '../../_lib/auth'

export async function POST(req: Request) {
  const current = await getCurrentUser({ refreshSession: true })
  if (!current.authenticated) {
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }

  const body = await req.json().catch(() => ({}))
  const screenings = body.screenings
  const supplements = body.supplements && typeof body.supplements === 'object' ? body.supplements : {}
  const sessionId = typeof body.sessionId === 'string' ? body.sessionId : ''

  if (!Array.isArray(screenings) || screenings.length === 0) {
    return Response.json({ error: '请完成核心量表后再提交。' }, { status: 400 })
  }

  const result = await backendRequest('/screening/batch', {
    method: 'POST',
    sessionToken: current.sessionToken,
    body: JSON.stringify({
      user_id: current.user.user_id,
      session_id: sessionId,
      screenings,
      supplements,
    }),
  })

  if (!result.ok) {
    return Response.json(
      { error: result.status === 400 ? '量表或补充答案格式不正确。' : '状态评估保存失败，请稍后再试。' },
      { status: result.status }
    )
  }

  return Response.json(result.data, { status: result.status })
}
