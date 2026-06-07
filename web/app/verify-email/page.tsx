import { AuthShell } from '../_components/auth-shell'
import { VerifyEmailClient } from '../_components/verify-email-client'

type VerifyEmailPageProps = {
  searchParams?: Promise<{ token?: string | string[] }> | { token?: string | string[] }
}

export default async function VerifyEmailPage({ searchParams }: VerifyEmailPageProps) {
  const params = searchParams ? await searchParams : {}
  const tokenParam = params.token
  const token = Array.isArray(tokenParam) ? tokenParam[0] || '' : tokenParam || ''

  return (
    <AuthShell
      title="验证邮箱"
      intro="完成验证后，就可以使用邮箱自助找回密码。"
      switchHref="/settings/account"
      switchText="返回账号设置"
    >
      <VerifyEmailClient token={token} />
    </AuthShell>
  )
}
