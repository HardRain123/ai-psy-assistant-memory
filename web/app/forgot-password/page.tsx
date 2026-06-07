import { redirect } from 'next/navigation'

import { AuthShell } from '../_components/auth-shell'
import { ForgotPasswordForm } from '../_components/forgot-password-form'
import { getCurrentUser } from '../api/_lib/auth'

export default async function ForgotPasswordPage() {
  const current = await getCurrentUser()
  if (current.authenticated) {
    redirect('/chat')
  }

  return (
    <AuthShell
      title="忘记密码"
      intro="输入注册邮箱后，系统会发送一次性重置链接。"
      switchHref="/login"
      switchText="想起来了？返回登录"
    >
      <ForgotPasswordForm />
    </AuthShell>
  )
}
