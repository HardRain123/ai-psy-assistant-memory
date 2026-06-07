import { backendRequest, clearSessionCookie, getCurrentUser } from '../_lib/auth'

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
      await clearSessionCookie()
      return Response.json(
        { error: '登录状态已失效，请重新登录；如果账号已停用，请联系管理员。' },
        { status: 401 }
      )
    }

    const userId = current.user.user_id
    const contextResult = await backendRequest(`/context/${encodeURIComponent(userId)}`, {
      method: 'GET',
      sessionToken: current.sessionToken,
    })
    const contextText =
      contextResult.ok && typeof contextResult.data?.context_text === 'string'
        ? contextResult.data.context_text
        : ''
    const recentScreening =
      contextResult.ok && typeof contextResult.data?.recent_screening === 'string'
        ? contextResult.data.recent_screening
        : ''
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
        response_mode: 'streaming',
        inputs: {
          user_id: userId,
          context: contextText,
          context_text: contextText,
          recent_screening: recentScreening,
        },
      }),
    })

    if (!res.ok || !res.body) {
      return Response.json(
        { error: '聊天服务暂时不可用，请稍后再试。' },
        { status: 502 }
      )
    }

    const encoder = new TextEncoder()
    const decoder = new TextDecoder()

    const stream = new ReadableStream({
      async start(controller) {
        const reader = res.body!.getReader()
        let buffer = ''
        let latestConversationId = typeof conversationId === 'string' ? conversationId : ''

        function emit(payload: Record<string, unknown>) {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`))
        }

        function handleEvent(raw: string) {
          if (!raw || raw === '[DONE]') return

          let event: Record<string, unknown>
          try {
            event = JSON.parse(raw)
          } catch {
            return
          }

          if (typeof event.conversation_id === 'string' && event.conversation_id) {
            latestConversationId = event.conversation_id
            emit({ type: 'conversation', conversationId: latestConversationId })
          }

          const eventName = typeof event.event === 'string' ? event.event : ''
          if (eventName === 'error') {
            emit({ type: 'error', error: '聊天服务暂时不可用，请稍后再试。' })
            return
          }

          if (typeof event.answer === 'string' && event.answer) {
            emit({ type: 'chunk', answer: event.answer })
          }

          if (eventName === 'message_end' || eventName === 'workflow_finished') {
            emit({ type: 'done', conversationId: latestConversationId })
          }
        }

        try {
          while (true) {
            const { done, value } = await reader.read()
            if (done) break

            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split(/\r?\n/)
            buffer = lines.pop() || ''

            for (const line of lines) {
              const trimmed = line.trim()
              if (!trimmed.startsWith('data:')) continue
              handleEvent(trimmed.slice(5).trim())
            }
          }

          if (buffer.trim().startsWith('data:')) {
            handleEvent(buffer.trim().slice(5).trim())
          }

          emit({ type: 'done', conversationId: latestConversationId })
        } catch {
          emit({ type: 'error', error: '聊天服务暂时不可用，请稍后再试。' })
        } finally {
          controller.close()
        }
      },
    })

    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
      },
    })
  } catch {
    return Response.json(
      { error: '聊天服务暂时不可用，请稍后再试。' },
      { status: 500 }
    )
  }
}
