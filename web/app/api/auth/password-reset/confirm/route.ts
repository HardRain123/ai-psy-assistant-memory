import { backendRequest, clearSessionCookie } from '../../../_lib/auth'

const INVALID_TOKEN_MESSAGE = '重置链接无效或已过期，请重新申请。'
const WEAK_PASSWORD_MESSAGE = '密码至少需要 8 个字符。'
const SERVICE_ERROR_MESSAGE = '密码重置服务暂时不可用，请稍后再试。'

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))
  const token = typeof body.token === 'string' ? body.token.trim() : ''
  const newPassword = typeof body.new_password === 'string' ? body.new_password : ''

  if (!token) {
    return Response.json({ error: INVALID_TOKEN_MESSAGE }, { status: 400 })
  }

  if (newPassword.length < 8) {
    return Response.json({ error: WEAK_PASSWORD_MESSAGE }, { status: 400 })
  }

  const result = await backendRequest('/internal/auth/password-reset/confirm', {
    method: 'POST',
    body: JSON.stringify({
      token,
      new_password: newPassword,
    }),
  })

  if (result.ok) {
    await clearSessionCookie()
    return Response.json({
      success: true,
      message: result.data?.message || '密码已重置，请使用新密码重新登录。',
    })
  }

  if (result.data?.error === 'weak_password') {
    return Response.json({ error: WEAK_PASSWORD_MESSAGE }, { status: 400 })
  }

  if (result.status === 400) {
    return Response.json({ error: INVALID_TOKEN_MESSAGE }, { status: 400 })
  }

  return Response.json({ error: SERVICE_ERROR_MESSAGE }, { status: 500 })
}
