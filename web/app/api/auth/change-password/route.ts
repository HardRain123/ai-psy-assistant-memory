import { backendRequest, clearSessionCookie, getSessionToken } from '../../_lib/auth'

export async function POST(req: Request) {
  const sessionToken = await getSessionToken()
  if (!sessionToken) {
    await clearSessionCookie()
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }

  const body = await req.json().catch(() => ({}))
  const currentPassword = typeof body.current_password === 'string' ? body.current_password : ''
  const newPassword = typeof body.new_password === 'string' ? body.new_password : ''

  if (newPassword.length < 8) {
    return Response.json({ error: '密码至少需要 8 个字符。' }, { status: 400 })
  }

  const result = await backendRequest('/internal/auth/change-password', {
    method: 'POST',
    sessionToken,
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  })

  if (result.ok) {
    await clearSessionCookie()
    return Response.json({
      success: true,
      message: result.data?.message || '密码已修改，请使用新密码重新登录。',
    })
  }

  if (result.status === 401) {
    return Response.json({ error: '当前密码不正确，请检查后再试。' }, { status: 401 })
  }

  if (result.data?.error === 'weak_password') {
    return Response.json({ error: '密码至少需要 8 个字符。' }, { status: 400 })
  }

  return Response.json({ error: '修改密码失败，请稍后再试。' }, { status: 500 })
}
