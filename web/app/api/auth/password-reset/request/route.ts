import { backendRequest } from '../../../_lib/auth'

const REQUEST_MESSAGE = '如果邮箱存在，重置链接会发送到该邮箱。'

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))

  await backendRequest('/internal/auth/password-reset/request', {
    method: 'POST',
    body: JSON.stringify({
      email: typeof body.email === 'string' ? body.email : '',
    }),
  })

  return Response.json({
    success: true,
    message: REQUEST_MESSAGE,
  })
}
