import { redirect } from 'next/navigation'

import { AuthShell } from '../_components/auth-shell'
import { LoginForm } from '../_components/login-form'
import { getCurrentUser } from '../api/_lib/auth'

export default async function LoginPage() {
  const current = await getCurrentUser()
  if (current.authenticated) {
    redirect('/chat')
  }

  return (
    <AuthShell
      title="登录"
      intro="登录后继续你的情绪整理和咨询式对话。"
      switchHref="/register"
      switchText="还没有账号？使用邀请码注册"
    >
      <LoginForm />
    </AuthShell>
  )
}
