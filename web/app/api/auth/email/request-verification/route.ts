import { backendRequest, clearSessionCookie, getSessionToken } from '../../../_lib/auth'

const REQUEST_MESSAGE = '如果邮箱可用，验证链接会发送到该邮箱。'

export async function POST(req: Request) {
  const sessionToken = await getSessionToken()
  if (!sessionToken) {
    await clearSessionCookie()
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }

  const body = await req.json().catch(() => ({}))
  const result = await backendRequest('/internal/auth/email/request-verification', {
    method: 'POST',
    sessionToken,
    body: JSON.stringify({
      email: typeof body.email === 'string' ? body.email : '',
    }),
  })

  if (result.ok) {
    return Response.json({
      success: true,
      message: result.data?.message || REQUEST_MESSAGE,
      email: result.data?.email,
      email_masked: result.data?.email_masked,
      email_verified: result.data?.email_verified,
    })
  }

  if (result.status === 401) {
    await clearSessionCookie()
    return Response.json({ error: '登录状态已失效，请重新登录。' }, { status: 401 })
  }

  if (result.data?.error === 'email_exists') {
    return Response.json({ error: '这个邮箱已经被注册，请换一个邮箱。' }, { status: 409 })
  }

  if (result.data?.error === 'invalid_email') {
    return Response.json({ error: '请输入有效的邮箱地址。' }, { status: 400 })
  }

  return Response.json({ error: '邮箱验证服务暂时不可用，请稍后再试。' }, { status: 500 })
}
