import { AuthShell } from '../_components/auth-shell'
import { ResetPasswordForm } from '../_components/reset-password-form'

type ResetPasswordPageProps = {
  searchParams?: Promise<{ token?: string | string[] }> | { token?: string | string[] }
}

export default async function ResetPasswordPage({ searchParams }: ResetPasswordPageProps) {
  const params = searchParams ? await searchParams : {}
  const tokenParam = params.token
  const token = Array.isArray(tokenParam) ? tokenParam[0] || '' : tokenParam || ''

  return (
    <AuthShell
      title="重置密码"
      intro="设置一个新的登录密码。"
      switchHref="/forgot-password"
      switchText="链接不可用？重新申请"
    >
      <ResetPasswordForm token={token} />
    </AuthShell>
  )
}
