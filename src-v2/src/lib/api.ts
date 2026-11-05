/** Тонкий клиент API. Токен доступа живёт только в памяти страницы,
 *  refresh-токен — в httpOnly-cookie, которую браузер отправляет сам. */

export interface User {
  id: string
  tab_no: string
  full_name: string
  position: string | null
  department: string | null
  role: string
  permissions: string[]
  status: string
  mfa_enabled: boolean
  must_change_password: boolean
  last_login_at: string | null
}

export interface TokenPair {
  access_token: string
  token_type: string
  expires_in: number
  user: User
  mfa_required: boolean
}

export interface MfaRequired {
  mfa_required: true
  challenge_token: string
  expires_in: number
  full_name: string
}

export interface Problem {
  code?: string
  detail?: string
  title?: string
  fields?: Record<string, string>
}

export class ApiError extends Error {
  status: number
  code: string
  fields: Record<string, string>

  constructor(status: number, problem: Problem) {
    super(problem.detail || problem.title || `Ошибка ${status}`)
    this.status = status
    this.code = problem.code || 'error'
    this.fields = problem.fields || {}
  }
}

export interface Employee {
  id: string
  tab_no: string
  full_name: string
  position: string | null
  department: string | null
  phone_e164: string | null
  email: string | null
  telegram_id: number | null
  otp_channel: string
  role: string
  status: string
  access_until: string | null
  has_credentials: boolean
  mfa_enabled: boolean
  last_login_at: string | null
  created_at: string
}

export interface AuditRecord {
  id: number
  at: string
  actor_tab_no: string | null
  actor_role: string | null
  action: string
  entity: string | null
  entity_id: string | null
  result: string
  ip: string | null
  method: string | null
  path: string | null
  detail: string | null
}

let accessToken: string | null = null
let refreshInFlight: Promise<TokenPair> | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  const isForm = typeof FormData !== 'undefined' && init.body instanceof FormData
  if (init.body && !isForm && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)

  const response = await fetch(path, {
    ...init,
    headers,
    credentials: 'include',
  })

  if (response.status === 401 && retry && !path.startsWith('/api/auth/')) {
    const refreshed = await tryRefresh()
    if (refreshed) return request<T>(path, init, false)
  }

  if (!response.ok) {
    let problem: Problem = {}
    try {
      problem = (await response.json()) as Problem
    } catch {
      problem = { detail: `Ошибка ${response.status}` }
    }
    throw new ApiError(response.status, problem)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function tryRefresh(): Promise<boolean> {
  try {
    const data = await request<TokenPair>('/api/auth/refresh', { method: 'POST' }, false)
    setAccessToken(data.access_token)
    return true
  } catch {
    setAccessToken(null)
    return false
  }
}

export const api = {
  async login(tab_no: string, password: string): Promise<TokenPair | MfaRequired> {
    const data = await request<TokenPair | MfaRequired>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ tab_no, password }),
    })
    if (!('mfa_required' in data) || !data.mfa_required) {
      setAccessToken((data as TokenPair).access_token)
    }
    return data
  },

  async verifyMfa(challenge_token: string, code: string): Promise<TokenPair> {
    const data = await request<TokenPair>('/api/auth/mfa/verify', {
      method: 'POST',
      body: JSON.stringify({ challenge_token, code }),
    })
    setAccessToken(data.access_token)
    return data
  },

  async refresh(): Promise<TokenPair> {
    // В StrictMode эффект монтируется дважды, и параллельный refresh
    // ротировал бы токен дважды (второй запрос — уже «старым» токеном)
    if (!refreshInFlight) {
      refreshInFlight = request<TokenPair>('/api/auth/refresh', { method: 'POST' }, false)
        .then((data) => {
          setAccessToken(data.access_token)
          return data
        })
        .finally(() => {
          refreshInFlight = null
        })
    }
    return refreshInFlight
  },

  async logout(): Promise<void> {
    try {
      await request('/api/auth/logout', { method: 'POST' }, false)
    } finally {
      setAccessToken(null)
    }
  },

  me: () => request<User>('/api/me'),

  registerStart: (tab_no: string) =>
    request<{
      delivery: string
      delivery_target: string | null
      expires_in: number
      next_step: string
      debug_code: string | null
    }>('/api/auth/register/start', { method: 'POST', body: JSON.stringify({ tab_no }) }),

  registerVerify: (tab_no: string, code: string) =>
    request<{ setup_token: string; expires_in: number }>('/api/auth/register/verify', {
      method: 'POST',
      body: JSON.stringify({ tab_no, code }),
    }),

  registerComplete: async (setup_token: string, password: string): Promise<TokenPair> => {
    const data = await request<TokenPair>('/api/auth/register/complete', {
      method: 'POST',
      body: JSON.stringify({ setup_token, password }),
    })
    setAccessToken(data.access_token)
    return data
  },

  changePassword: (current_password: string, new_password: string) =>
    request<{ message: string }>('/api/me/password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),

  totpEnroll: () =>
    request<{ secret: string; otpauth_uri: string; qr_svg: string }>('/api/me/mfa/totp/enroll', {
      method: 'POST',
    }),

  totpConfirm: (code: string) =>
    request<{ codes: string[]; note: string }>('/api/me/mfa/totp/confirm', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),

  sessions: () =>
    request<Array<{ id: string; created_at: string; last_seen_at: string | null; ip: string | null; user_agent: string | null; current: boolean }>>(
      '/api/me/sessions',
    ),

  revokeSession: (id: string) =>
    request<{ message: string }>(`/api/me/sessions/${id}`, { method: 'DELETE' }),

  employees: (search = '') =>
    request<{ items: Employee[]; total: number }>(
      `/api/employees${search ? `?search=${encodeURIComponent(search)}` : ''}`,
    ),

  createEmployee: (payload: {
    tab_no: string
    full_name: string
    role: string
    position?: string
    otp_channel?: string
    telegram_id?: number | null
  }) => request<Employee>('/api/employees', { method: 'POST', body: JSON.stringify(payload) }),

  blockEmployee: (id: string) => request<Employee>(`/api/employees/${id}/block`, { method: 'POST' }),
  unblockEmployee: (id: string) => request<Employee>(`/api/employees/${id}/unblock`, { method: 'POST' }),
  updateEmployee: (id: string, payload: Record<string, unknown>) =>
    request<Employee>(`/api/employees/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  dismissEmployee: (id: string) =>
    request<Employee>(`/api/employees/${id}`, { method: 'DELETE' }),
  resetPassword: (id: string) =>
    request<{ temp_password: string; note: string }>(`/api/employees/${id}/reset-password`, {
      method: 'POST',
    }),
  resendInvite: (id: string) =>
    request<{ delivery: string; expires_in: number; debug_code: string | null }>(
      `/api/employees/${id}/resend-invite`,
      { method: 'POST' },
    ),

  audit: (params: { limit?: number; result?: string } = {}) => {
    const query = new URLSearchParams()
    query.set('limit', String(params.limit ?? 50))
    if (params.result) query.set('result', params.result)
    return request<{ items: AuditRecord[]; total: number }>(`/api/audit?${query.toString()}`)
  },
}

/** Доступ к низкоуровневому запросу для других модулей (например, ГИС). */
export const apiRequest = request
