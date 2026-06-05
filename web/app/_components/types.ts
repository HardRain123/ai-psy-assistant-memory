export type User = {
  user_id: string
  username: string
  is_admin: boolean
}

export type Message = {
  role: 'user' | 'assistant'
  content: string
}

export type Invite = {
  id: number
  status: 'active' | 'used' | 'revoked' | string
  note?: string | null
  created_at: string
  used_at?: string | null
  revoked_at?: string | null
  used_by_username?: string | null
}
