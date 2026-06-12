import { backendRequest, setSessionCookie } from '../../_lib/auth'

function registerErrorMessage(status: number, detail: unknown) {
  const message = typeof detail === 'string' ? detail : ''

  if (message === 'email_exists') {
    return '这个邮箱已经被注册，请换一个邮箱。'
  }

  if (message === 'invalid_email') {
    return '请输入有效的邮箱地址。'
  }

  if (status === 409 || message === 'username_exists' || message === 'username already exists') {
    return '这个账号已经被注册，请换一个账号名。'
  }

  if (message === 'weak_password' || message === 'password must be at least 8 characters') {
    return '密码至少需要 8 个字符。'
  }

  if (
    message === 'invalid_username' ||
    message === 'username must be 3-64 characters using letters, numbers, _ . @ or -'
  ) {
    return '账号需要 3-64 个字符，只能包含字母、数字、下划线、点、@ 或短横线。'
  }

  if (message === 'invalid_invite_code' || message === 'invalid invite code') {
    return '邀请码不存在，请检查后重新输入。'
  }

  if (message === 'inactive_invite_code' || message === 'invite code is not active') {
    return '邀请码已被使用或已失效，请联系管理员重新生成。'
  }

  if (message === 'required_consents_missing') {
    return '请逐项确认年龄要求和全部必要授权。'
  }

  if (message === 'policy_version_outdated') {
    return '授权条款已经更新，请刷新页面后重新确认。'
  }

  if (status === 400) {
    return '注册信息不完整，请检查邀请码、账号、邮箱和密码。'
  }

  if (status === 401 || status === 403) {
    return '邀请码不可用或已失效。'
  }

  return '注册服务暂时不可用，请稍后再试。'
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}))
  if (
    !body.inviteCode ||
    !body.username ||
    !body.email ||
    !body.password ||
    !body.policyVersion
  ) {
    return Response.json({ error: '请填写注册信息并逐项完成授权确认。' }, { status: 400 })
  }

  const result = await backendRequest('/internal/auth/register', {
    method: 'POST',
    body: JSON.stringify({
      username: body.username,
      email: body.email,
      password: body.password,
      inviteCode: body.inviteCode,
      policyVersion: body.policyVersion,
      adultConfirmed: body.adultConfirmed === true,
      aiServiceConsent: body.aiServiceConsent === true,
      sensitiveDataConsent: body.sensitiveDataConsent === true,
      conversationStorageConsent: body.conversationStorageConsent === true,
      longTermMemoryConsent: body.longTermMemoryConsent === true,
      humanSafetyReviewConsent: body.humanSafetyReviewConsent === true,
    }),
  })

  if (!result.ok) {
    const error = registerErrorMessage(result.status, result.data?.detail || result.data?.error)
    return Response.json({ error }, { status: result.status })
  }

  const loginResult = await backendRequest('/internal/auth/login', {
    method: 'POST',
    body: JSON.stringify({
      username: body.username,
      password: body.password,
    }),
  })

  if (!loginResult.ok || !loginResult.data?.session_token) {
    return Response.json(
      { error: '注册成功，但自动登录失败。请返回登录页重新登录。' },
      { status: 500 }
    )
  }

  await setSessionCookie(loginResult.data.session_token)

  return Response.json({
    success: true,
    authenticated: true,
    user: loginResult.data.user,
    expires_at: loginResult.data.expires_at,
  })
}
