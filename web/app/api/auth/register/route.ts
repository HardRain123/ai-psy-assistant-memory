import { backendRequest, setSessionCookie } from '../../_lib/auth'

function registerErrorMessage(status: number, detail: unknown) {
  const message = typeof detail === 'string' ? detail : ''

  if (status === 409 || message === 'username already exists') {
    return '这个账号已经被注册，请换一个账号名。'
  }

  if (message === 'password must be at least 8 characters') {
    return '密码至少需要 8 个字符。'
  }

  if (message === 'username must be 3-64 characters using letters, numbers, _ . @ or -') {
    return '账号需为 3-64 个字符，只能包含字母、数字、下划线、点、@ 或短横线。'
  }

  if (message === 'invalid invite code') {
    return '邀请码不存在，请检查后重新输入。'
  }

  if (message === 'invite code is not active') {
    return '邀请码已被使用或已失效，请联系管理员重新生成。'
  }

  if (status === 400) {
    return '注册信息不完整，请检查邀请码、账号和密码。'
  }

  if (status === 401 || status === 403) {
    return '邀请码不可用或已失效。'
  }

  return '注册服务暂时不可用，请稍后再试。'
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))
  if (!body.inviteCode || !body.username || !body.password) {
    return Response.json({ error: '请填写邀请码、账号和密码。' }, { status: 400 })
  }

  const result = await backendRequest('/internal/auth/register', {
    method: 'POST',
    body: JSON.stringify({
      username: body.username,
      password: body.password,
      inviteCode: body.inviteCode,
    }),
  })

  if (!result.ok) {
    const error = registerErrorMessage(result.status, result.data?.detail || result.data?.error)
    return Response.json(
      { error },
      { status: result.status }
    )
  }

  const loginResult = await backendRequest('/internal/auth/login', {
    method: 'POST',
    body: JSON.stringify({
      username: body.username,
      password: body.password,
    }),
  })

  if (!loginResult.ok || !loginResult.data?.session_token) {
    return Response.json(
      { error: '注册成功，但自动登录失败。请返回登录页重新登录。' },
      { status: 500 }
    )
  }

  await setSessionCookie(loginResult.data.session_token)

  return Response.json({
    success: true,
    authenticated: true,
    user: loginResult.data.user,
    expires_at: loginResult.data.expires_at,
  })
}
