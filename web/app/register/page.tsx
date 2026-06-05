import { redirect } from 'next/navigation'

import { AuthShell } from '../_components/auth-shell'
import { RegisterForm } from '../_components/register-form'
import { getCurrentUser } from '../api/_lib/auth'

export default async function RegisterPage() {
  const current = await getCurrentUser()
  if (current.authenticated) {
    redirect('/chat')
  }

  return (
    <AuthShell
      title="邀请码注册"
      intro="当前是小范围测试版，需要管理员提供的邀请码。"
      switchHref="/login"
      switchText="已有账号？去登录"
    >
      <RegisterForm />
    </AuthShell>
  )
}
