import { backendRequest } from '../../_lib/auth'

let cachedConfig: unknown = null

export async function GET() {
  if (cachedConfig) {
    return Response.json(cachedConfig)
  }

  const result = await backendRequest('/screening/config', {
    method: 'GET',
  })

  if (!result.ok) {
    return Response.json(
      { error: '无法读取状态评估配置，请稍后再试。' },
      { status: result.status }
    )
  }

  cachedConfig = result.data
  return Response.json(result.data, { status: result.status })
}
