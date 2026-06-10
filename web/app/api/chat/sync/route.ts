import { backendRequest, clearSessionCookie, getCurrentUser } from '../../_lib/auth'

type TranscriptMessage = {
  role: 'user' | 'assistant'
  content: string
  turnId: string
  syncStatus: string
}

type DifyHistoryMessage = {
  id: string
  query: string
  answer: string
  createdAt: number
}

function asString(value: unknown) {
  return typeof value === 'string' ? value.trim() : ''
}

function transcriptMessages(data: unknown): TranscriptMessage[] {
  if (!data || typeof data !== 'object' || !('messages' in data)) return []
  const rawMessages = (data as { messages?: unknown }).messages
  if (!Array.isArray(rawMessages)) return []

  return rawMessages.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const role = (item as { role?: unknown }).role
    const content = asString((item as { content?: unknown }).content)
    if ((role !== 'user' && role !== 'assistant') || !content) return []
    return [
      {
        role,
        content,
        turnId: asString((item as { turn_id?: unknown }).turn_id),
        syncStatus: asString((item as { sync_status?: unknown }).sync_status) || 'complete',
      },
    ]
  })
}

function latestIncompleteTurn(messages: TranscriptMessage[]) {
  const latest = messages[messages.length - 1]
  if (!latest) return null

  if (latest.role === 'user') {
    return { turnId: latest.turnId, query: latest.content }
  }

  if (latest.syncStatus && latest.syncStatus !== 'complete') {
    for (let index = messages.length - 2; index >= 0; index -= 1) {
      const candidate = messages[index]
      if (candidate.role !== 'user') continue
      if (!latest.turnId || !candidate.turnId || candidate.turnId === latest.turnId) {
        return { turnId: latest.turnId || candidate.turnId, query: candidate.content }
      }
    }
  }

  return null
}

function difyMessages(data: unknown): DifyHistoryMessage[] {
  if (!data || typeof data !== 'object') return []
  const rawMessages =
    (data as { data?: unknown }).data ||
    (data as { messages?: unknown }).messages ||
    (data as { items?: unknown }).items
  if (!Array.isArray(rawMessages)) return []

  return rawMessages
    .flatMap((item) => {
      if (!item || typeof item !== 'object') return []
      const answer = asString((item as { answer?: unknown }).answer)
      if (!answer) return []
      const id = asString((item as { id?: unknown }).id) || asString((item as { message_id?: unknown }).message_id)
      const createdAt = Number((item as { created_at?: unknown }).created_at || 0)
      return [
        {
          id,
          query: asString((item as { query?: unknown }).query),
          answer,
          createdAt: Number.isFinite(createdAt) ? createdAt : 0,
        },
      ]
    })
    .sort((a, b) => a.createdAt - b.createdAt)
}

function selectDifyAnswer(messages: DifyHistoryMessage[], query: string) {
  const normalizedQuery = query.trim()
  const exactMatches = messages.filter((item) => item.query.trim() === normalizedQuery)
  if (exactMatches.length > 0) return exactMatches[exactMatches.length - 1]
  return messages[messages.length - 1] || null
}

async function saveAssistantMessage({
  userId,
  sessionId,
  turnId,
  answer,
  externalMessageId,
  conversationId,
  sessionToken,
}: {
  userId: string
  sessionId: string
  turnId: string
  answer: string
  externalMessageId: string
  conversationId: string
  sessionToken: string
}) {
  return backendRequest('/session-message', {
    method: 'POST',
    sessionToken,
    body: JSON.stringify({
      user_id: userId,
      session_id: sessionId,
      role: 'assistant',
      content: answer,
      turn_id: turnId || undefined,
      external_message_id: externalMessageId || undefined,
      sync_status: 'complete',
      dify_conversation_id: conversationId || undefined,
    }),
  })
}

export async function POST(req: Request) {
  try {
    const body = await req.json().catch(() => ({}))
    const current = await getCurrentUser({ refreshSession: true })
    if (!current.authenticated) {
      await clearSessionCookie()
      return Response.json({ error: 'unauthorized' }, { status: 401 })
    }

    const userId = current.user.user_id
    const sessionStatus = await backendRequest(`/session/status/${encodeURIComponent(userId)}`, {
      method: 'GET',
      sessionToken: current.sessionToken,
    })
    const sessionId =
      sessionStatus.ok && typeof sessionStatus.data?.session_id === 'string'
        ? sessionStatus.data.session_id
        : ''
    if (!sessionId) {
      return Response.json({ synced: false, reason: 'session_missing' })
    }

    const transcript = await backendRequest(`/session-transcript/${encodeURIComponent(sessionId)}`, {
      method: 'GET',
      sessionToken: current.sessionToken,
    })
    const target = transcript.ok ? latestIncompleteTurn(transcriptMessages(transcript.data)) : null
    if (!target) {
      return Response.json({ synced: false, reason: 'already_complete' })
    }

    const conversationId =
      asString((body as { conversationId?: unknown }).conversationId) ||
      asString(sessionStatus.data?.dify_conversation_id)
    if (!conversationId) {
      return Response.json({ synced: false, reason: 'conversation_missing' })
    }

    const difyApiUrl = process.env.DIFY_API_URL
    const difyApiKey = process.env.DIFY_API_KEY
    if (!difyApiUrl || !difyApiKey) {
      return Response.json({ synced: false, reason: 'dify_unavailable' }, { status: 503 })
    }

    const params = new URLSearchParams({
      user: userId,
      conversation_id: conversationId,
      limit: '5',
    })
    const difyResponse = await fetch(`${difyApiUrl}/messages?${params.toString()}`, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${difyApiKey}`,
      },
      cache: 'no-store',
    })
    if (!difyResponse.ok) {
      return Response.json({ synced: false, reason: 'dify_history_unavailable' }, { status: 502 })
    }

    const selected = selectDifyAnswer(difyMessages(await difyResponse.json().catch(() => ({}))), target.query)
    if (!selected) {
      return Response.json({ synced: false, reason: 'answer_missing' })
    }

    const saved = await saveAssistantMessage({
      userId,
      sessionId,
      turnId: target.turnId,
      answer: selected.answer,
      externalMessageId: selected.id,
      conversationId,
      sessionToken: current.sessionToken,
    })
    if (!saved.ok) {
      return Response.json({ synced: false, reason: 'backend_save_failed' }, { status: 502 })
    }

    return Response.json({ synced: true, turnId: target.turnId, externalMessageId: selected.id })
  } catch {
    return Response.json({ synced: false, reason: 'sync_failed' }, { status: 500 })
  }
}
