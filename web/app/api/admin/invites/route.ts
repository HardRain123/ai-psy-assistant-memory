import { backendRequest, getCurrentUser } from '../../_lib/auth'

export async function GET() {
  const current = await getCurrentUser({ refreshSession: true })
  if (!current.authenticated) {
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }
  if (!current.user.is_admin) {
    return Response.json({ error: '没有管理员权限。' }, { status: 403 })
  }

  const result = await backendRequest('/internal/admin/invites', {
    method: 'GET',
    sessionToken: current.sessionToken,
  })
  if (!result.ok) {
    return Response.json({ error: '无法读取邀请码，请稍后再试。' }, { status: result.status })
  }

  return Response.json(result.data, { status: result.status })
}

export async function POST(req: Request) {
  const current = await getCurrentUser({ refreshSession: true })
  if (!current.authenticated) {
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }
  if (!current.user.is_admin) {
    return Response.json({ error: '没有管理员权限。' }, { status: 403 })
  }

  const body = await req.json().catch(() => ({}))
  const result = await backendRequest('/internal/admin/invites', {
    method: 'POST',
    sessionToken: current.sessionToken,
    body: JSON.stringify({
      note: body.note || '',
      expires_at: body.expires_at || null,
    }),
  })
  if (!result.ok) {
    return Response.json({ error: '创建邀请码失败，请稍后再试。' }, { status: result.status })
  }

  return Response.json(result.data, { status: result.status })
}

export async function DELETE(req: Request) {
  const current = await getCurrentUser({ refreshSession: true })
  if (!current.authenticated) {
    return Response.json({ error: '请先登录。' }, { status: 401 })
  }
  if (!current.user.is_admin) {
    return Response.json({ error: '没有管理员权限。' }, { status: 403 })
  }

  const body = await req.json().catch(() => ({}))
  const result = await backendRequest('/internal/admin/invites', {
    method: 'DELETE',
    sessionToken: current.sessionToken,
    body: JSON.stringify({ invite_id: body.invite_id }),
  })
  if (!result.ok) {
    return Response.json({ error: '撤销邀请码失败，请稍后再试。' }, { status: result.status })
  }

  return Response.json(result.data, { status: result.status })
}
