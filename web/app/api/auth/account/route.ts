import { backendRequest, clearSessionCookie, getSessionToken } from '../../_lib/auth'

export async function GET() {
  const sessionToken = await getSessionToken()
  if (!sessionToken) {
    await clearSessionCookie()
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }

  const result = await backendRequest('/internal/auth/account', {
    method: 'GET',
    sessionToken,
  })

  if (!result.ok) {
    if (result.status === 401) {
      await clearSessionCookie()
      return Response.json({ error: '登录状态已失效，请重新登录。' }, { status: 401 })
    }
    return Response.json({ error: '无法读取账号信息，请稍后再试。' }, { status: 500 })
  }

  return Response.json({
    success: true,
    account: result.data?.account,
  })
}
