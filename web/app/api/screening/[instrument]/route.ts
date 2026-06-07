import { backendRequest, getCurrentUser } from '../../_lib/auth'

type RouteContext = {
  params: Promise<{ instrument: string }>
}

export async function POST(req: Request, context: RouteContext) {
  const current = await getCurrentUser({ refreshSession: true })
  if (!current.authenticated) {
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }

  const body = await req.json().catch(() => ({}))
  const answers = body.answers
  const sessionId = typeof body.sessionId === 'string' ? body.sessionId : ''
  const { instrument } = await context.params

  if (!Array.isArray(answers)) {
    return Response.json({ error: '请完成量表后再提交。' }, { status: 400 })
  }

  const result = await backendRequest(`/screening/${encodeURIComponent(instrument)}`, {
    method: 'POST',
    sessionToken: current.sessionToken,
    body: JSON.stringify({
      user_id: current.user.user_id,
      session_id: sessionId,
      answers,
    }),
  })

  if (!result.ok) {
    return Response.json(
      { error: result.status === 400 ? '量表答案格式不正确。' : '状态评估保存失败，请稍后再试。' },
      { status: result.status }
    )
  }

  return Response.json(result.data, { status: result.status })
}
