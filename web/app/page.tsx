'use client'

import { useEffect, useRef, useState } from 'react'

type Message = {
  role: 'user' | 'assistant'
  content: string
}

function getOrCreateUserId() {
  const key = 'psy_user_id'
  let userId = localStorage.getItem(key)

  if (!userId) {
    userId = `anonymous_${crypto.randomUUID()}`
    localStorage.setItem(key, userId)
  }

  return userId
}

export default function HomePage() {
  const [accepted, setAccepted] = useState(false)
  const [userId, setUserId] = useState('')
  const [conversationId, setConversationId] = useState('')
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content:
        '你好，我会尽量用克制、具体的方式陪你整理。今天可以先从你现在最想说的一件事开始。',
    },
  ])

  const bottomRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const savedAccepted = localStorage.getItem('psy_safety_accepted')
    const savedConversationId = localStorage.getItem('psy_conversation_id')

    if (savedAccepted === 'true') {
      setAccepted(true)
    }

    if (savedConversationId) {
      setConversationId(savedConversationId)
    }

    setUserId(getOrCreateUserId())
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function sendMessage() {
    const text = input.trim()
    if (!text || loading) return

    setInput('')
    setLoading(true)

    setMessages((prev) => [...prev, { role: 'user', content: text }])

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: text,
          userId,
          conversationId,
        }),
      })

      const data = await res.json()

      if (!res.ok) {
        throw new Error(data.error || '请求失败')
      }

      if (data.conversationId) {
        setConversationId(data.conversationId)
        localStorage.setItem('psy_conversation_id', data.conversationId)
      }

      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.answer || '我刚才没有拿到有效回复，可以再说一次吗？',
        },
      ])
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: '刚才连接失败了，可能是服务暂时不可用。你可以稍后再试一次。',
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  function acceptNotice() {
    localStorage.setItem('psy_safety_accepted', 'true')
    setAccepted(true)
  }

  if (!accepted) {
    return (
      <main className="min-h-screen bg-zinc-50 flex items-center justify-center px-4">
        <section className="max-w-xl w-full bg-white rounded-2xl shadow-sm border border-zinc-200 p-6">
          <h1 className="text-2xl font-semibold text-zinc-900">
            AI 情绪整理助手
          </h1>

          <p className="mt-4 text-zinc-700 leading-7">
            这个工具用于帮你整理情绪、复盘卡住的地方，并在一次对话结束时留下一个很小的行动。
          </p>

          <div className="mt-4 rounded-xl bg-amber-50 border border-amber-200 p-4 text-sm text-amber-900 leading-6">
            它不是医疗诊断工具，不替代心理咨询师、精神科医生或紧急救援。
            如果你正在出现自伤、自杀或伤害他人的紧急风险，请优先联系现实中的可信任的人，或拨打当地紧急电话。
          </div>

          <button
            onClick={acceptNotice}
            className="mt-6 w-full rounded-xl bg-zinc-900 text-white py-3 font-medium hover:bg-zinc-800"
          >
            我已了解，开始今天的咨询
          </button>
        </section>
      </main>
    )
  }

  return (
    <main className="min-h-screen bg-zinc-50 flex flex-col">
      <header className="border-b border-zinc-200 bg-white px-4 py-3">
        <div className="max-w-3xl mx-auto">
          <h1 className="text-lg font-semibold text-zinc-900">
            AI 情绪整理助手
          </h1>
          <p className="text-xs text-zinc-500 mt-1">
            每天一次，约 50 分钟。不是医疗诊断或紧急救援服务。
          </p>
        </div>
      </header>

      <section className="flex-1 px-4 py-6 overflow-y-auto">
        <div className="max-w-3xl mx-auto space-y-4">
          {messages.map((msg, index) => (
            <div
              key={index}
              className={
                msg.role === 'user'
                  ? 'flex justify-end'
                  : 'flex justify-start'
              }
            >
              <div
                className={
                  msg.role === 'user'
                    ? 'max-w-[80%] rounded-2xl bg-zinc-900 text-white px-4 py-3 leading-7'
                    : 'max-w-[80%] rounded-2xl bg-white border border-zinc-200 text-zinc-900 px-4 py-3 leading-7'
                }
              >
                {msg.content}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="rounded-2xl bg-white border border-zinc-200 text-zinc-500 px-4 py-3">
                正在整理你的话……
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </section>

      <footer className="border-t border-zinc-200 bg-white px-4 py-4">
        <div className="max-w-3xl mx-auto flex gap-3">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                sendMessage()
              }
            }}
            placeholder="说说你现在最想整理的一件事……"
            className="flex-1 resize-none rounded-xl border border-zinc-300 px-4 py-3 outline-none focus:ring-2 focus:ring-zinc-300 min-h-[52px] max-h-32"
          />

          <button
            onClick={sendMessage}
            disabled={loading || !input.trim()}
            className="rounded-xl bg-zinc-900 text-white px-5 py-3 font-medium disabled:opacity-40"
          >
            发送
          </button>
        </div>
      </footer>
    </main>
  )
}