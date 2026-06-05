'use client'

import { useRouter } from 'next/navigation'
import { KeyboardEvent, useRef, useState } from 'react'

import { CrisisNotice, EmptyState, NonMedicalNotice, PrivacyNotice } from './notices'
import type { Message, User } from './types'

export function ChatClient({ user }: { user: User }) {
  const router = useRouter()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [conversationId, setConversationId] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const bottomRef = useRef<HTMLDivElement | null>(null)

  function scrollToBottomSoon() {
    window.setTimeout(() => {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, 0)
  }

  async function sendMessage() {
    const text = input.trim()
    if (!text || sending) return

    setError('')
    setInput('')
    setSending(true)
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    scrollToBottomSoon()

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, conversationId: conversationId || undefined }),
      })
      const data = await res.json().catch(() => ({}))

      if (res.status === 401) {
        setMessages([])
        setConversationId('')
        router.replace('/login')
        router.refresh()
        return
      }

      if (!res.ok) {
        throw new Error(data.error || 'chat_failed')
      }

      if (data.conversationId) {
        setConversationId(data.conversationId)
      }

      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.answer || '我刚才没有拿到有效回复，可以再说一次吗？',
        },
      ])
      scrollToBottomSoon()
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: '刚才连接失败了，可能是服务暂时不可用。你可以稍后再试一次。',
        },
      ])
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
          <h1 className="text-base font-semibold text-zinc-900">咨询式对话</h1>
          <p className="mt-1 text-sm text-zinc-500">
            {user.username}，可以从现在最想整理的一件事开始。
          </p>
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

          {sending && (
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
            <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}
          <div className="flex flex-col gap-3 sm:flex-row">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={onInputKeyDown}
              placeholder="说说你现在最想整理的一件事..."
              className="min-h-[56px] max-h-32 flex-1 resize-none rounded-lg border border-zinc-300 px-4 py-3 outline-none focus:ring-2 focus:ring-zinc-300"
            />
            <button
              onClick={sendMessage}
              disabled={sending || !input.trim()}
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
