import { redirect } from 'next/navigation'

import { AppHeader } from '../_components/app-header'
import { ChatClient } from '../_components/chat-client'
import type { Message } from '../_components/types'
import { backendRequest, getCurrentUser } from '../api/_lib/auth'

type ChatPageProps = {
  searchParams?: Promise<{ showSession?: string | string[] }> | { showSession?: string | string[] }
}

type SessionHistoryItem = {
  session_id: string
  status?: string
  stage?: string
  started_at?: string
  ended_at?: string
  message_count?: number
}

function transcriptMessages(data: unknown): Message[] {
  if (!data || typeof data !== 'object' || !('messages' in data)) {
    return []
  }

  const rawMessages = (data as { messages?: unknown }).messages
  if (!Array.isArray(rawMessages)) {
    return []
  }

  return rawMessages.flatMap((item) => {
    if (!item || typeof item !== 'object') {
      return []
    }

    const role = (item as { role?: unknown }).role
    const content = (item as { content?: unknown }).content
    if ((role !== 'user' && role !== 'assistant') || typeof content !== 'string' || !content.trim()) {
      return []
    }

    return [
      {
        role,
        content,
        turn_id: typeof (item as { turn_id?: unknown }).turn_id === 'string' ? (item as { turn_id: string }).turn_id : '',
        external_message_id:
          typeof (item as { external_message_id?: unknown }).external_message_id === 'string'
            ? (item as { external_message_id: string }).external_message_id
            : '',
        sync_status:
          typeof (item as { sync_status?: unknown }).sync_status === 'string'
            ? (item as { sync_status: string }).sync_status
            : 'complete',
      },
    ]
  })
}

function sessionHistory(data: unknown): SessionHistoryItem[] {
  if (!data || typeof data !== 'object' || !('sessions' in data)) {
    return []
  }

  const rawSessions = (data as { sessions?: unknown }).sessions
  if (!Array.isArray(rawSessions)) {
    return []
  }

  return rawSessions.flatMap((item) => {
    if (!item || typeof item !== 'object') {
      return []
    }

    const sessionId = (item as { session_id?: unknown }).session_id
    if (typeof sessionId !== 'string' || !sessionId) {
      return []
    }

    return [
      {
        session_id: sessionId,
        status: typeof (item as { status?: unknown }).status === 'string' ? (item as { status: string }).status : '',
        stage: typeof (item as { stage?: unknown }).stage === 'string' ? (item as { stage: string }).stage : '',
        started_at:
          typeof (item as { started_at?: unknown }).started_at === 'string'
            ? (item as { started_at: string }).started_at
            : '',
        ended_at:
          typeof (item as { ended_at?: unknown }).ended_at === 'string'
            ? (item as { ended_at: string }).ended_at
            : '',
        message_count:
          typeof (item as { message_count?: unknown }).message_count === 'number'
            ? (item as { message_count: number }).message_count
            : 0,
      },
    ]
  })
}

function firstParam(value: string | string[] | undefined) {
  if (Array.isArray(value)) return value[0] || ''
  return value || ''
}

function normalizedContent(value: string) {
  return value.trim().replace(/\s+/g, ' ')
}

function messagesOverlap(left: string, right: string) {
  const a = normalizedContent(left)
  const b = normalizedContent(right)
  if (!a || !b) return false
  return a === b || a.startsWith(b) || b.startsWith(a)
}

function mergeAssistantMessage(existing: Message, incoming: Message): Message {
  const useIncoming = normalizedContent(incoming.content).length >= normalizedContent(existing.content).length
  const primary = useIncoming ? incoming : existing
  const secondary = useIncoming ? existing : incoming

  return {
    ...primary,
    turn_id: primary.turn_id || secondary.turn_id || '',
    external_message_id: primary.external_message_id || secondary.external_message_id || '',
    sync_status:
      existing.sync_status === 'complete' || incoming.sync_status === 'complete'
        ? 'complete'
        : primary.sync_status || secondary.sync_status || 'complete',
  }
}

function coalesceAssistantMessages(messages: Message[]) {
  const coalesced: Message[] = []

  for (const message of messages) {
    const previous = coalesced[coalesced.length - 1]
    if (!previous || previous.role !== 'assistant' || message.role !== 'assistant') {
      coalesced.push(message)
      continue
    }

    const sameTurn = Boolean(previous.turn_id && previous.turn_id === message.turn_id)
    const overlap = messagesOverlap(previous.content, message.content)
    if (sameTurn || overlap) {
      coalesced[coalesced.length - 1] = mergeAssistantMessage(previous, message)
      continue
    }

    coalesced.push(message)
  }

  return coalesced
}

export default async function ChatPage({ searchParams }: ChatPageProps = {}) {
  const current = await getCurrentUser()
  if (!current.authenticated) {
    redirect('/login')
  }
  const params = searchParams ? await searchParams : {}
  const requestedDisplaySessionId = firstParam(params.showSession)

  const sessionStatus = await backendRequest(`/session/status/${encodeURIComponent(current.user.user_id)}`, {
    method: 'GET',
    sessionToken: current.sessionToken,
  })
  const sessionId =
    sessionStatus.ok && typeof sessionStatus.data?.session_id === 'string'
      ? sessionStatus.data.session_id
      : ''
  const transcript = sessionId
    ? await backendRequest(`/session-transcript/${encodeURIComponent(sessionId)}`, {
        method: 'GET',
        sessionToken: current.sessionToken,
      })
    : null
  const history = await backendRequest(`/session-history/${encodeURIComponent(current.user.user_id)}?limit=12`, {
    method: 'GET',
    sessionToken: current.sessionToken,
  })
  const historyItems = history.ok ? sessionHistory(history.data) : []
  let displaySessionId = sessionId
  let initialMessages = transcript?.ok ? coalesceAssistantMessages(transcriptMessages(transcript.data)) : []

  if (requestedDisplaySessionId && requestedDisplaySessionId !== sessionId) {
    const requestedTranscript = await backendRequest(
      `/session-transcript/${encodeURIComponent(requestedDisplaySessionId)}?user_id=${encodeURIComponent(current.user.user_id)}`,
      {
        method: 'GET',
        sessionToken: current.sessionToken,
      }
    )
    const requestedMessages = requestedTranscript.ok
      ? coalesceAssistantMessages(transcriptMessages(requestedTranscript.data))
      : []
    if (requestedMessages.length > 0) {
      displaySessionId = requestedDisplaySessionId
      initialMessages = requestedMessages
    }
  } else if (initialMessages.length === 0 && historyItems.length > 0) {
    const fallbackSession = historyItems.find((item) => item.session_id !== sessionId) || historyItems[0]
    const fallbackTranscript = await backendRequest(
      `/session-transcript/${encodeURIComponent(fallbackSession.session_id)}?user_id=${encodeURIComponent(current.user.user_id)}`,
      {
        method: 'GET',
        sessionToken: current.sessionToken,
      }
    )
    const fallbackMessages = fallbackTranscript.ok
      ? coalesceAssistantMessages(transcriptMessages(fallbackTranscript.data))
      : []
    if (fallbackMessages.length > 0) {
      displaySessionId = fallbackSession.session_id
      initialMessages = fallbackMessages
    }
  }

  return (
    <main className="min-h-screen bg-zinc-50">
      <AppHeader user={current.user} />
      <ChatClient
        key={`${sessionId || 'no-session'}:${displaySessionId || 'current'}`}
        user={current.user}
        initialSessionStatus={sessionStatus.ok ? sessionStatus.data : null}
        initialMessages={initialMessages}
        initialMessagesSessionId={displaySessionId}
        sessionHistory={historyItems}
      />
    </main>
  )
}
