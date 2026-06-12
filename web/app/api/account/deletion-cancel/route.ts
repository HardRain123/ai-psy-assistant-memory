import { cookies } from 'next/headers'

import { backendRequest } from '../../_lib/auth'
import {
  DELETION_REQUEST_COOKIE,
  DELETION_TOKEN_COOKIE,
} from '../_lib/deletion'

export async function POST() {
  const cookieStore = await cookies()
  const requestId = cookieStore.get(DELETION_REQUEST_COOKIE)?.value || ''
  const cancellationToken = cookieStore.get(DELETION_TOKEN_COOKIE)?.value || ''
  if (!requestId || !cancellationToken) {
    return Response.json({ error: 'deletion_request_not_found' }, { status: 404 })
  }
  const result = await backendRequest('/internal/account/deletion-cancel', {
    method: 'POST',
    body: JSON.stringify({
      request_id: requestId,
      cancellation_token: cancellationToken,
    }),
  })
  if (result.ok) {
    cookieStore.delete(DELETION_REQUEST_COOKIE)
    cookieStore.delete(DELETION_TOKEN_COOKIE)
  }
  return Response.json(result.data, { status: result.status })
}
