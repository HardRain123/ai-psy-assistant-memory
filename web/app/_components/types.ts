export type User = {
  user_id: string
  username: string
  is_admin: boolean
}

export type Account = {
  user_id: string
  username: string
  email: string
  email_masked: string
  has_email: boolean
  email_verified: boolean
  email_verified_at?: string | null
  is_admin: boolean
  created_at?: string | null
  updated_at?: string | null
  last_login_at?: string | null
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

export type AdminUser = {
  user_id: string
  username: string
  email_masked?: string
  has_email?: boolean
  email_verified?: boolean
  email_verified_at?: string | null
  is_admin: boolean
  status: 'active' | 'disabled' | 'admin' | string
  disabled_at?: string | null
  last_login_at?: string | null
  created_at?: string | null
  updated_at?: string | null
  counts?: {
    sessions?: number
    messages?: number
    memories?: number
    handoff_documents?: number
  }
}
