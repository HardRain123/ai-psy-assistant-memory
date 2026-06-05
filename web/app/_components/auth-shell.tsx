import Link from 'next/link'

import { NonMedicalNotice } from './notices'

export function AuthShell({
  title,
  intro,
  switchHref,
  switchText,
  children,
}: {
  title: string
  intro: string
  switchHref: string
  switchText: string
  children: React.ReactNode
}) {
  return (
    <main className="min-h-screen bg-zinc-50 px-4 py-10">
      <section className="mx-auto flex min-h-[calc(100vh-5rem)] w-full max-w-md flex-col justify-center">
        <div className="rounded-lg border border-zinc-200 bg-white p-6 shadow-sm">
          <h1 className="text-2xl font-semibold text-zinc-900">AI 情绪整理助手</h1>
          <h2 className="mt-6 text-lg font-semibold text-zinc-900">{title}</h2>
          <p className="mt-2 text-sm leading-6 text-zinc-600">{intro}</p>
          <div className="mt-6">{children}</div>
          <Link
            href={switchHref}
            className="mt-5 block text-center text-sm font-medium text-zinc-700 underline-offset-4 hover:underline"
          >
            {switchText}
          </Link>
        </div>

        <div className="mt-5 rounded-lg border border-zinc-200 bg-white p-4">
          <NonMedicalNotice compact />
        </div>
      </section>
    </main>
  )
}
