import { backendRequest, clearSessionCookie, getCurrentUser } from '../_lib/auth'

type MessageSyncStatus = 'streaming' | 'complete' | 'error'

async function getCurrentSessionId(userId: string, sessionToken: string) {
  const result = await backendRequest(`/session/status/${encodeURIComponent(userId)}`, {
    method: 'GET',
    sessionToken,
  })
  return result.ok && typeof result.data?.session_id === 'string' ? result.data.session_id : ''
}

async function saveSessionMessage({
  userId,
  sessionId,
  role,
  content,
  sessionToken,
  turnId,
  externalMessageId,
  syncStatus = 'complete',
  difyConversationId,
}: {
  userId: string
  sessionId: string
  role: 'user' | 'assistant'
  content: string
  sessionToken: string
  turnId?: string
  externalMessageId?: string
  syncStatus?: MessageSyncStatus
  difyConversationId?: string
}) {
  if (!sessionId || (!content.trim() && !difyConversationId)) return

  return backendRequest('/session-message', {
    method: 'POST',
    sessionToken,
    body: JSON.stringify({
      user_id: userId,
      session_id: sessionId,
      role,
      content,
      turn_id: turnId || undefined,
      external_message_id: externalMessageId || undefined,
      sync_status: syncStatus,
      dify_conversation_id: difyConversationId || undefined,
    }),
  })
}

function createTurnId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `turn-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

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
    const sessionId = await getCurrentSessionId(userId, current.sessionToken)
    const turnId = createTurnId()
    const userMessageSave = await saveSessionMessage({
      userId,
      sessionId,
      role: 'user',
      content: message.trim(),
      sessionToken: current.sessionToken,
      turnId,
      syncStatus: 'complete',
      difyConversationId: typeof conversationId === 'string' ? conversationId : undefined,
    })
    const metadataSupported = Boolean(userMessageSave?.ok && userMessageSave.data?.turn_id === turnId)

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
        let latestDifyMessageId = ''
        let assistantAnswer = ''
        let lastPersistedLength = 0
        let lastPersistedAt = 0
        let lastPersistedStatus = ''
        let persistedConversationId = ''
        let streamCompleted = false
        let responseClosed = false

        function emit(payload: Record<string, unknown>) {
          if (responseClosed) return
          try {
            controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`))
          } catch {
            responseClosed = true
          }
        }

        async function persistAssistantSnapshot(syncStatus: MessageSyncStatus) {
          if (!assistantAnswer.trim()) return
          if (!metadataSupported && syncStatus !== 'complete') return
          if (syncStatus === 'complete' && lastPersistedStatus === 'complete') return
          const now = Date.now()
          const shouldPersist =
            syncStatus === 'complete' ||
            syncStatus === 'error' ||
            assistantAnswer.length - lastPersistedLength >= 240 ||
            now - lastPersistedAt >= 1500
          if (!shouldPersist) return

          await saveSessionMessage({
            userId,
            sessionId,
            role: 'assistant',
            content: assistantAnswer,
            sessionToken: current.sessionToken,
            turnId,
            externalMessageId: latestDifyMessageId,
            syncStatus,
            difyConversationId: latestConversationId,
          })
          lastPersistedLength = assistantAnswer.length
          lastPersistedAt = now
          lastPersistedStatus = syncStatus
        }

        async function persistConversationId() {
          if (!latestConversationId || latestConversationId === persistedConversationId) return
          await saveSessionMessage({
            userId,
            sessionId,
            role: 'assistant',
            content: '',
            sessionToken: current.sessionToken,
            difyConversationId: latestConversationId,
          })
          persistedConversationId = latestConversationId
        }

        async function handleEvent(raw: string) {
          if (!raw || raw === '[DONE]') return

          let event: Record<string, unknown>
          try {
            event = JSON.parse(raw)
          } catch {
            return
          }

          if (typeof event.conversation_id === 'string' && event.conversation_id) {
            latestConversationId = event.conversation_id
            await persistConversationId()
            emit({ type: 'conversation', conversationId: latestConversationId })
          }
          const rawMessageId =
            typeof event.message_id === 'string'
              ? event.message_id
              : typeof event.id === 'string'
                ? event.id
                : ''
          if (rawMessageId) {
            latestDifyMessageId = rawMessageId
          }

          const eventName = typeof event.event === 'string' ? event.event : ''
          if (eventName === 'error') {
            await persistAssistantSnapshot('error')
            emit({ type: 'error', error: '聊天服务暂时不可用，请稍后再试。' })
            return
          }

          if (typeof event.answer === 'string' && event.answer) {
            assistantAnswer += event.answer
            emit({ type: 'chunk', answer: event.answer })
            await persistAssistantSnapshot('streaming')
          }

          if (eventName === 'message_end' || eventName === 'workflow_finished') {
            streamCompleted = true
            await persistAssistantSnapshot('complete')
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
              await handleEvent(trimmed.slice(5).trim())
            }
          }

          if (buffer.trim().startsWith('data:')) {
            await handleEvent(buffer.trim().slice(5).trim())
          }

          streamCompleted = true
          await persistAssistantSnapshot('complete')
          emit({ type: 'done', conversationId: latestConversationId })
        } catch {
          await persistAssistantSnapshot('error')
          emit({ type: 'error', error: '聊天服务暂时不可用，请稍后再试。' })
        } finally {
          if (assistantAnswer.trim() && lastPersistedStatus !== 'complete' && lastPersistedStatus !== 'error') {
            await persistAssistantSnapshot(streamCompleted ? 'complete' : 'streaming')
          }
          if (!responseClosed) {
            try {
              controller.close()
            } catch {
              responseClosed = true
            }
          }
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
