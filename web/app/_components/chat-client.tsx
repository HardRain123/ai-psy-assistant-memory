'use client'

import { useRouter } from 'next/navigation'
import { KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'

import { CrisisNotice, EmptyState, NonMedicalNotice, PrivacyNotice } from './notices'
import type { Message, User } from './types'

type SessionStatus = {
  session_id?: string
  status?: string
  remaining_minutes?: number
  elapsed_minutes?: number
  can_continue?: boolean
  message?: string
  timer_started?: boolean
  session_stage?: string
}

type SessionHistoryItem = {
  session_id: string
  status?: string
  stage?: string
  started_at?: string
  ended_at?: string
  message_count?: number
}

const SESSION_SECONDS = 50 * 60

function sessionTimerStarted(status?: SessionStatus | null) {
  return (
    status?.timer_started !== false &&
    status?.status !== 'pending' &&
    status?.session_stage !== 'not_started'
  )
}

function remainingSecondsFromStatus(status?: SessionStatus | null) {
  if (!sessionTimerStarted(status)) return null
  const minutes = Number(status?.remaining_minutes)
  if (!Number.isFinite(minutes)) return null
  return Math.max(0, Math.round(minutes * 60))
}

function formatRemaining(seconds: number | null, timerStarted = true) {
  if (!timerStarted) return '发送第一条消息后开始计时'
  if (seconds === null) return '剩余时间获取中'
  const safeSeconds = Math.max(0, seconds)
  const minutes = Math.floor(safeSeconds / 60)
  const restSeconds = safeSeconds % 60
  return `${minutes}:${String(restSeconds).padStart(2, '0')}`
}

function timerTone(seconds: number | null, timerStarted = true) {
  if (!timerStarted) return 'border-zinc-200 bg-zinc-100 text-zinc-600'
  if (seconds === null) return 'border-zinc-200 bg-zinc-100 text-zinc-600'
  if (seconds <= 5 * 60) return 'border-red-200 bg-red-50 text-red-700'
  if (seconds <= 10 * 60) return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-emerald-200 bg-emerald-50 text-emerald-700'
}

function formatSessionTime(value?: string) {
  if (!value) return '未开始'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function ChatClient({
  user,
  initialSessionStatus = null,
  initialMessages = [],
  initialMessagesSessionId = '',
  sessionHistory = [],
}: {
  user: User
  initialSessionStatus?: SessionStatus | null
  initialMessages?: Message[]
  initialMessagesSessionId?: string
  sessionHistory?: SessionHistoryItem[]
}) {
  const router = useRouter()
  const [messages, setMessages] = useState<Message[]>(initialMessages)
  const [input, setInput] = useState('')
  const [conversationId, setConversationId] = useState('')
  const [remainingSeconds, setRemainingSeconds] = useState<number | null>(
    remainingSecondsFromStatus(initialSessionStatus)
  )
  const [timerStarted, setTimerStarted] = useState(sessionTimerStarted(initialSessionStatus))
  const [sessionCanContinue, setSessionCanContinue] = useState(initialSessionStatus?.can_continue !== false)
  const [sending, setSending] = useState(false)
  const [resettingSession, setResettingSession] = useState(false)
  const [error, setError] = useState('')
  const [authActionRequired, setAuthActionRequired] = useState(false)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const timeLabel = useMemo(() => formatRemaining(remainingSeconds, timerStarted), [remainingSeconds, timerStarted])
  const sessionId = initialSessionStatus?.session_id || ''
  const [showingHistoricalMessages, setShowingHistoricalMessages] = useState(
    Boolean(initialMessagesSessionId && sessionId && initialMessagesSessionId !== sessionId)
  )
  const conversationStorageKey = sessionId
    ? `psy-chat-conversation:${user.user_id}:${sessionId}`
    : `psy-chat-conversation:${user.user_id}`

  useEffect(() => {
    if (!timerStarted) return
    if (remainingSeconds === null) return
    const timer = window.setInterval(() => {
      setRemainingSeconds((prev) => {
        if (prev === null) return prev
        const next = Math.max(0, prev - 1)
        if (next === 0) {
          setSessionCanContinue(false)
        }
        return next
      })
    }, 1000)
    return () => window.clearInterval(timer)
  }, [remainingSeconds, timerStarted])

  useEffect(() => {
    const storedConversationId = window.localStorage.getItem(conversationStorageKey)
    if (storedConversationId) {
      setConversationId(storedConversationId)
    }
  }, [conversationStorageKey])

  useEffect(() => {
    if (!conversationId) return
    window.localStorage.setItem(conversationStorageKey, conversationId)
  }, [conversationId, conversationStorageKey])

  useEffect(() => {
    if (initialMessages.length === 0) return
    scrollToBottomSoon()
  }, [initialMessages.length])

  function scrollToBottomSoon() {
    window.setTimeout(() => {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, 0)
  }

  function startTimerIfNeeded() {
    if (timerStarted) return

    const minutes = Number(initialSessionStatus?.remaining_minutes)
    const initialSeconds = Number.isFinite(minutes) ? Math.max(0, Math.round(minutes * 60)) : SESSION_SECONDS
    setTimerStarted(true)
    setRemainingSeconds((prev) => prev ?? initialSeconds)
  }

  async function resetSessionToYesterday() {
    if (resettingSession) return
    if (!window.confirm('仅用于管理员测试，会把当前会话改为昨天并刷新为新会话，继续吗？')) {
      return
    }

    setError('')
    setAuthActionRequired(false)
    setResettingSession(true)

    try {
      const res = await fetch('/api/chat/admin-reset-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages }),
      })
      const data = await res.json().catch(() => ({}))

      if (res.status === 401) {
        setError(typeof data.error === 'string' ? data.error : '请先登录。')
        setAuthActionRequired(true)
        setConversationId('')
        window.localStorage.removeItem(conversationStorageKey)
        return
      }

      if (!res.ok) {
        throw new Error(typeof data.error === 'string' ? data.error : 'admin_reset_session_failed')
      }

      const shiftedSessionId =
        data && typeof data.shifted_session_id === 'string' ? data.shifted_session_id : ''
      window.localStorage.removeItem(conversationStorageKey)
      setConversationId('')
      if (shiftedSessionId) {
        router.replace(`/chat?showSession=${encodeURIComponent(shiftedSessionId)}`)
      } else {
        router.refresh()
      }
    } catch {
      setError('重置会话失败，请稍后再试。')
    } finally {
      setResettingSession(false)
    }
  }

  function updateLastAssistantMessage(content: string) {
    setMessages((prev) => {
      const next = [...prev]
      for (let index = next.length - 1; index >= 0; index -= 1) {
        if (next[index].role === 'assistant') {
          next[index] = { ...next[index], content }
          return next
        }
      }
      return [...next, { role: 'assistant', content }]
    })
    scrollToBottomSoon()
  }

  async function sendMessage() {
    const text = input.trim()
    if (!text || sending || !sessionCanContinue) return

    setError('')
    setAuthActionRequired(false)
    setInput('')
    setSending(true)
    setShowingHistoricalMessages(false)
    setMessages((prev) => [
      ...(showingHistoricalMessages ? [] : prev),
      { role: 'user', content: text },
      { role: 'assistant', content: '正在连接咨询引擎...' },
    ])
    scrollToBottomSoon()

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, conversationId: conversationId || undefined }),
      })

      if (res.status === 401) {
        const data = await res.json().catch(() => ({}))
        const authMessage =
          typeof data.error === 'string'
            ? data.error
            : '登录状态已失效，请重新登录；如果账号已停用，请联系管理员。'
        setError(authMessage)
        setAuthActionRequired(true)
        setConversationId('')
        updateLastAssistantMessage(authMessage)
        return
      }

      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.error || 'chat_failed')
      }

      startTimerIfNeeded()

      const contentType = res.headers.get('Content-Type') || ''
      if (!contentType.includes('text/event-stream') || !res.body) {
        const data = await res.json().catch(() => ({}))
        if (data.conversationId) {
          setConversationId(data.conversationId)
        }
        updateLastAssistantMessage(data.answer || '我刚才没有拿到有效回复，可以再说一次吗？')
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let answer = ''
      let streamError = ''

      function handleEvent(raw: string) {
        if (!raw) return

        let event: { type?: string; answer?: string; conversationId?: string; error?: string }
        try {
          event = JSON.parse(raw)
        } catch {
          return
        }

        if (event.conversationId) {
          setConversationId(event.conversationId)
        }
        if (event.type === 'error') {
          streamError = event.error || '聊天服务暂时不可用，请稍后再试。'
        }
        if (event.type === 'chunk' && event.answer) {
          answer += event.answer
          updateLastAssistantMessage(answer)
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split(/\n\n/)
        buffer = events.pop() || ''

        for (const event of events) {
          const line = event
            .split(/\r?\n/)
            .map((item) => item.trim())
            .find((item) => item.startsWith('data:'))
          if (line) {
            handleEvent(line.slice(5).trim())
          }
        }
      }

      if (buffer.trim().startsWith('data:')) {
        handleEvent(buffer.trim().slice(5).trim())
      }

      if (!answer) {
        updateLastAssistantMessage(streamError || '我刚才没有拿到有效回复，可以再说一次吗？')
      }
    } catch {
      updateLastAssistantMessage('刚才连接失败了，可能是服务暂时不可用。你可以稍后再试一次。')
    } finally {
      setSending(false)
    }
  }

  function onInputKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void sendMessage()
    }
  }

  return (
    <div className="mx-auto grid max-w-6xl gap-4 px-4 py-5 lg:grid-cols-[1fr_320px]">
      <section className="flex min-h-[calc(100vh-124px)] flex-col rounded-lg border border-zinc-200 bg-white">
        <div className="border-b border-zinc-200 px-4 py-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h1 className="text-base font-semibold text-zinc-900">咨询式对话</h1>
              <p className="mt-1 text-sm text-zinc-500">
                {user.username}，可以从现在最想整理的一件事开始。
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 sm:justify-end">
              {user.is_admin && (
                <button
                  type="button"
                  onClick={resetSessionToYesterday}
                  disabled={resettingSession}
                  className="rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {resettingSession ? '重置中...' : '重置到昨天'}
                </button>
              )}
              <div className={`w-fit rounded-lg border px-3 py-2 text-sm font-medium ${timerTone(remainingSeconds, timerStarted)}`}>
                {timerStarted ? <>本次会话还剩 {timeLabel}</> : timeLabel}
              </div>
            </div>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {messages.length === 0 && (
            <EmptyState
              title="还没有开始对话"
              body="你可以写下一件具体的事、一种情绪，或一句现在卡住的话。"
            />
          )}

          {messages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
            >
              <div
                className={
                  message.role === 'user'
                    ? 'max-w-[86%] rounded-lg bg-zinc-900 px-4 py-3 leading-7 text-white'
                    : 'max-w-[86%] rounded-lg border border-zinc-200 bg-zinc-50 px-4 py-3 leading-7 text-zinc-900'
                }
              >
                {message.content}
              </div>
            </div>
          ))}

          {sending && messages[messages.length - 1]?.role !== 'assistant' && (
            <div className="flex justify-start">
              <div className="rounded-lg border border-zinc-200 bg-zinc-50 px-4 py-3 text-sm text-zinc-500">
                正在整理你的话...
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-zinc-200 p-4">
          {error && (
            <div className="mb-3 flex flex-col gap-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 sm:flex-row sm:items-center sm:justify-between">
              <p>{error}</p>
              {authActionRequired && (
                <button
                  onClick={() => router.replace('/login')}
                  className="w-fit rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-100"
                >
                  重新登录
                </button>
              )}
            </div>
          )}
          {!sessionCanContinue && (
            <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              本次咨询时间已结束，明天可以开始下一次正式咨询。
            </div>
          )}
          <div className="flex flex-col gap-3 sm:flex-row">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={onInputKeyDown}
              placeholder="说说你现在最想整理的一件事..."
              disabled={!sessionCanContinue}
              className="min-h-[56px] max-h-32 flex-1 resize-none rounded-lg border border-zinc-300 px-4 py-3 outline-none focus:ring-2 focus:ring-zinc-300"
            />
            <button
              onClick={sendMessage}
              disabled={sending || !input.trim() || !sessionCanContinue}
              className="rounded-lg bg-zinc-900 px-5 py-3 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40"
            >
              {sending ? '发送中...' : '发送'}
            </button>
          </div>
        </div>
      </section>

      <aside className="space-y-4">
        {sessionHistory.length > 0 && (
          <div className="rounded-lg border border-zinc-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-zinc-900">历史会话</h2>
            <div className="mt-3 space-y-2">
              {sessionHistory.map((item) => {
                const selected = item.session_id === initialMessagesSessionId
                return (
                  <button
                    key={item.session_id}
                    type="button"
                    onClick={() => router.replace(`/chat?showSession=${encodeURIComponent(item.session_id)}`)}
                    className={
                      selected
                        ? 'w-full rounded-lg border border-zinc-900 bg-zinc-900 px-3 py-2 text-left text-sm text-white'
                        : 'w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-left text-sm text-zinc-700 hover:bg-zinc-50'
                    }
                  >
                    <span className="block font-medium">{formatSessionTime(item.started_at)}</span>
                    <span className={selected ? 'mt-1 block text-xs text-zinc-200' : 'mt-1 block text-xs text-zinc-500'}>
                      {item.message_count || 0} 条消息
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        )}
        <CrisisNotice />
        <PrivacyNotice />
        <div className="rounded-lg border border-zinc-200 bg-white p-4">
          <NonMedicalNotice compact />
        </div>
      </aside>
    </div>
  )
}
