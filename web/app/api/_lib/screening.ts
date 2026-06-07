import { backendRequest } from './auth'

export async function requestScreeningBootstrap(userId: string, sessionToken: string) {
  const queryResult = await backendRequest(`/screening/bootstrap?user_id=${encodeURIComponent(userId)}`, {
    method: 'GET',
    sessionToken,
  })

  if (queryResult.ok || queryResult.status !== 404) {
    return queryResult
  }

  return backendRequest(`/screening/bootstrap/${encodeURIComponent(userId)}`, {
    method: 'GET',
    sessionToken,
  })
}
