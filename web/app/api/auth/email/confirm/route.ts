import { backendRequest } from '../../../_lib/auth'

const INVALID_TOKEN_MESSAGE = '验证链接无效或已过期，请重新申请。'

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))
  const token = typeof body.token === 'string' ? body.token.trim() : ''

  if (!token) {
    return Response.json({ error: INVALID_TOKEN_MESSAGE }, { status: 400 })
  }

  const result = await backendRequest('/internal/auth/email/confirm', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })

  if (result.ok) {
    return Response.json({
      success: true,
      message: result.data?.message || '邮箱已验证。',
      email: result.data?.email,
      email_verified_at: result.data?.email_verified_at,
    })
  }

  if (result.status === 400) {
    return Response.json({ error: INVALID_TOKEN_MESSAGE }, { status: 400 })
  }

  return Response.json({ error: '邮箱验证服务暂时不可用，请稍后再试。' }, { status: 500 })
}
