import { backendRequest, clearSessionCookie, getCurrentUser } from '../../_lib/auth'

type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
}

function normalizeMessages(body: unknown): ChatMessage[] {
  if (!body || typeof body !== 'object' || !('messages' in body)) {
    return []
  }

  const rawMessages = (body as { messages?: unknown }).messages
  if (!Array.isArray(rawMessages)) {
    return []
  }

  const messages: ChatMessage[] = []
  for (const item of rawMessages) {
    if (!item || typeof item !== 'object') {
      continue
    }

    const role = (item as { role?: unknown }).role
    const content = (item as { content?: unknown }).content
    if ((role !== 'user' && role !== 'assistant') || typeof content !== 'string' || !content.trim()) {
      continue
    }

    messages.push({ role, content: content.trim() })
  }

  return messages.slice(-100)
}

async function sessionHasTranscript(sessionId: string, userId: string, sessionToken: string) {
  const transcript = await backendRequest(
    `/session-transcript/${encodeURIComponent(sessionId)}?user_id=${encodeURIComponent(userId)}`,
    {
      method: 'GET',
      sessionToken,
    }
  )
  return transcript.ok && Array.isArray(transcript.data?.messages) && transcript.data.messages.length > 0
}

async function saveClientTranscript(messages: ChatMessage[], sessionId: string, userId: string, sessionToken: string) {
  let saved = 0
  for (const message of messages) {
    const result = await backendRequest('/session-message', {
      method: 'POST',
      sessionToken,
      body: JSON.stringify({
        user_id: userId,
        session_id: sessionId,
        role: message.role,
        content: message.content,
      }),
    })
    if (result.ok && result.data?.success) {
      saved += 1
    }
  }
  return saved
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))
  const clientMessages = normalizeMessages(body)
  const current = await getCurrentUser({ refreshSession: true })
  if (!current.authenticated) {
    await clearSessionCookie()
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }

  if (!current.user.is_admin) {
    return Response.json({ error: '没有管理员权限。' }, { status: 403 })
  }

  const result = await backendRequest('/internal/admin/self/session/reset-to-yesterday', {
    method: 'POST',
    sessionToken: current.sessionToken,
  })

  if (result.ok) {
    const shiftedSessionId =
      typeof result.data?.shifted_session_id === 'string' ? result.data.shifted_session_id : ''
    if (
      shiftedSessionId &&
      clientMessages.length > 0 &&
      !(await sessionHasTranscript(shiftedSessionId, current.user.user_id, current.sessionToken))
    ) {
      const saved = await saveClientTranscript(
        clientMessages,
        shiftedSessionId,
        current.user.user_id,
        current.sessionToken
      )
      return Response.json({ ...result.data, client_messages_saved: saved }, { status: result.status })
    }
  }

  return Response.json(result.data, { status: result.status })
}
