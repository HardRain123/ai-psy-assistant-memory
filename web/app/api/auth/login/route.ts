import { backendRequest, setSessionCookie } from '../../_lib/auth'

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))
  if (!body.username || !body.password) {
    return Response.json({ error: '请输入账号和密码。' }, { status: 400 })
  }

  const result = await backendRequest('/internal/auth/login', {
    method: 'POST',
    body: JSON.stringify({
      username: body.username,
      password: body.password,
    }),
  })

  if (!result.ok || !result.data?.session_token) {
    const error =
      result.status === 400 || result.status === 401
        ? '账号或密码不正确，请检查后再试。'
        : '登录服务暂时不可用，请稍后再试。'
    return Response.json(
      { error },
      { status: result.status || 401 }
    )
  }

  await setSessionCookie(result.data.session_token)

  return Response.json({
    authenticated: true,
    user: result.data.user,
    expires_at: result.data.expires_at,
  })
}
