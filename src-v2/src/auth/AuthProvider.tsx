import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, setAccessToken } from '../lib/api'
import type { MfaRequired, User } from '../lib/api'

interface AuthContextValue {
  user: User | null
  initializing: boolean
  login: (tab_no: string, password: string) => Promise<MfaRequired | null>
  verifyMfa: (challenge: string, code: string) => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
  applyUser: (user: User) => void
  can: (permission: string) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [initializing, setInitializing] = useState(true)

  // При старте пробуем восстановить сессию по httpOnly-cookie.
  useEffect(() => {
    let cancelled = false
    api
      .refresh()
      .then((data) => {
        if (!cancelled) setUser(data.user)
      })
      .catch(() => {
        setAccessToken(null)
      })
      .finally(() => {
        if (!cancelled) setInitializing(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (tab_no: string, password: string) => {
    const data = await api.login(tab_no, password)
    if ('mfa_required' in data && data.mfa_required) {
      return data as MfaRequired
    }
    const pair = data as { user: User }
    setUser(pair.user)
    return null
  }, [])

  const verifyMfa = useCallback(async (challenge: string, code: string) => {
    const pair = await api.verifyMfa(challenge, code)
    setUser(pair.user)
  }, [])

  const logout = useCallback(async () => {
    await api.logout()
    setUser(null)
  }, [])

  const refreshUser = useCallback(async () => {
    const fresh = await api.me()
    setUser(fresh)
  }, [])

  const applyUser = useCallback((next: User) => setUser(next), [])

  const can = useCallback(
    (permission: string) => Boolean(user?.permissions?.includes(permission)),
    [user],
  )

  const value = useMemo(
    () => ({ user, initializing, login, verifyMfa, logout, refreshUser, applyUser, can }),
    [user, initializing, login, verifyMfa, logout, refreshUser, applyUser, can],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth должен использоваться внутри AuthProvider')
  return context
}
