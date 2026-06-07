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
}

function remainingSecondsFromStatus(status?: SessionStatus | null) {
  const minutes = Number(status?.remaining_minutes)
  if (!Number.isFinite(minutes)) return null
  return Math.max(0, Math.round(minutes * 60))
}

function formatRemaining(seconds: number | null) {
  if (seconds === null) return '剩余时间获取中'
  const safeSeconds = Math.max(0, seconds)
  const minutes = Math.floor(safeSeconds / 60)
  const restSeconds = safeSeconds % 60
  return `${minutes}:${String(restSeconds).padStart(2, '0')}`
}

function timerTone(seconds: number | null) {
  if (seconds === null) return 'border-zinc-200 bg-zinc-100 text-zinc-600'
  if (seconds <= 5 * 60) return 'border-red-200 bg-red-50 text-red-700'
  if (seconds <= 10 * 60) return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-emerald-200 bg-emerald-50 text-emerald-700'
}

export function ChatClient({
  user,
  initialSessionStatus = null,
}: {
  user: User
  initialSessionStatus?: SessionStatus | null
}) {
  const router = useRouter()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [conversationId, setConversationId] = useState('')
  const [remainingSeconds, setRemainingSeconds] = useState<number | null>(
    remainingSecondsFromStatus(initialSessionStatus)
  )
  const [sessionCanContinue, setSessionCanContinue] = useState(initialSessionStatus?.can_continue !== false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [authActionRequired, setAuthActionRequired] = useState(false)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const timeLabel = useMemo(() => formatRemaining(remainingSeconds), [remainingSeconds])

  useEffect(() => {
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
  }, [remainingSeconds])

  function scrollToBottomSoon() {
    window.setTimeout(() => {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, 0)
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
    setMessages((prev) => [
      ...prev,
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
            <div className={`w-fit rounded-lg border px-3 py-2 text-sm font-medium ${timerTone(remainingSeconds)}`}>
              本次会话还剩 {timeLabel}
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
        <CrisisNotice />
        <PrivacyNotice />
        <div className="rounded-lg border border-zinc-200 bg-white p-4">
          <NonMedicalNotice compact />
        </div>
      </aside>
    </div>
  )
}
