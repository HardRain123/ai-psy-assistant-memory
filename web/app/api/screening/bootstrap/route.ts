import { getCurrentUser } from '../../_lib/auth'
import { requestScreeningBootstrap } from '../../_lib/screening'

export async function GET() {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }

  const result = await requestScreeningBootstrap(current.user.user_id, current.sessionToken)

  if (!result.ok) {
    return Response.json(
      { error: '无法读取状态评估初始化数据，请稍后再试。' },
      { status: result.status }
    )
  }

  return Response.json(result.data, { status: result.status })
}
