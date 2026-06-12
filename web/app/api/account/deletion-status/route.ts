import { cookies } from 'next/headers'

import { backendRequest } from '../../_lib/auth'
import {
  DELETION_REQUEST_COOKIE,
  DELETION_TOKEN_COOKIE,
} from '../_lib/deletion'

export async function GET() {
  const cookieStore = await cookies()
  const requestId = cookieStore.get(DELETION_REQUEST_COOKIE)?.value || ''
  const cancellationToken = cookieStore.get(DELETION_TOKEN_COOKIE)?.value || ''
  if (!requestId || !cancellationToken) {
    return Response.json({ error: 'deletion_request_not_found' }, { status: 404 })
  }
  const params = new URLSearchParams({
    request_id: requestId,
    cancellation_token: cancellationToken,
  })
  const result = await backendRequest(`/internal/account/deletion-status?${params.toString()}`, {
    method: 'GET',
  })
  return Response.json(result.data, { status: result.status })
}
