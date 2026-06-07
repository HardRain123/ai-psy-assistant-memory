import { backendRequest, clearSessionCookie, getSessionToken } from '../../_lib/auth'

export async function POST() {
  const sessionToken = await getSessionToken()
  if (!sessionToken) {
    await clearSessionCookie()
    return Response.json({ success: true })
  }

  const result = await backendRequest('/internal/auth/logout-all', {
    method: 'POST',
    sessionToken,
  })

  await clearSessionCookie()

  if (!result.ok && result.status >= 500) {
    return Response.json({ error: '退出全部设备失败，请稍后再试。' }, { status: 500 })
  }

  return Response.json({
    success: true,
    message: result.data?.message || '已退出全部设备。',
  })
}
