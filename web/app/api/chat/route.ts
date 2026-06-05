import { getCurrentUser } from '../_lib/auth'

export async function POST(req: Request) {
  try {
    const body = await req.json().catch(() => ({}))
    const { message, conversationId } = body
    const allowedKeys = new Set(['message', 'conversationId'])
    const unexpectedKeys = Object.keys(body).filter((key) => !allowedKeys.has(key))

    if (unexpectedKeys.length > 0) {
      return Response.json(
        { error: '请求格式不正确。' },
        { status: 400 }
      )
    }

    if (typeof message !== 'string' || !message.trim()) {
      return Response.json(
        { error: '请输入要发送的内容。' },
        { status: 400 }
      )
    }

    const current = await getCurrentUser({ refreshSession: true })
    if (!current.authenticated) {
      return Response.json(
        { error: '请先登录。' },
        { status: 401 }
      )
    }

    const userId = current.user.user_id
    const difyApiUrl = process.env.DIFY_API_URL
    const difyApiKey = process.env.DIFY_API_KEY

    if (!difyApiUrl || !difyApiKey) {
      return Response.json(
        { error: '聊天服务暂时不可用，请稍后再试。' },
        { status: 503 }
      )
    }

    const res = await fetch(`${difyApiUrl}/chat-messages`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${difyApiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        query: message.trim(),
        user: userId,
        conversation_id: typeof conversationId === 'string' ? conversationId : '',
        response_mode: 'blocking',
        inputs: {
          user_id: userId,
        },
      }),
    })

    const data = await res.json()

    if (!res.ok) {
      return Response.json(
        { error: '聊天服务暂时不可用，请稍后再试。' },
        { status: 502 }
      )
    }

    return Response.json({
      answer: data.answer || '',
      conversationId: data.conversation_id || (typeof conversationId === 'string' ? conversationId : ''),
    })
  } catch {
    return Response.json(
      { error: '聊天服务暂时不可用，请稍后再试。' },
      { status: 500 }
    )
  }
}
