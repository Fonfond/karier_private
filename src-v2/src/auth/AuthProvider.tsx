import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError, api, setAccessToken } from '../lib/api'
import type { MfaRequired, User } from '../lib/api'

interface AuthContextValue {
  user: User | null
  initializing: boolean
  /** Нет сети (или сервер недоступен при старте): работаем на сохранённых данных. */
  offline: boolean
  login: (tab_no: string, password: string) => Promise<MfaRequired | null>
  verifyMfa: (challenge: string, code: string) => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
  applyUser: (user: User) => void
  can: (permission: string) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

// Подсказка «сессия была» — чтобы на первом визите не дёргать /auth/refresh
// без cookie: браузер писал бы 401 в консоль, хотя это обычный первый вход.
const SESSION_HINT = 'karier-session'
// Последний известный пользователь — для холодного старта без сети.
// Хранится только профиль (id, таб. номер, ФИО, права), без токенов;
// чистится при выходе и при ответе 401.
const LAST_USER_KEY = 'karier-last-user'

/** Итог восстановления сессии при старте приложения. */
export type SessionRestore =
  | { kind: 'authenticated'; user: User; clearSession: false }
  | { kind: 'unauthenticated'; clearSession: true }
  | { kind: 'offline'; user: User | null; clearSession: false }
  | { kind: 'degraded'; user: User | null; clearSession: false }

/** Сервер явно отказал в сессии — только это ведёт на экран входа. */
export function isUnauthorizedError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401
}

/** Сетевая ошибка (нет сети, обрыв, прерванный запрос) — сессию не трогаем. */
export function isNetworkError(error: unknown): boolean {
  if (typeof error === 'object' && error !== null) {
    const name = (error as { name?: unknown }).name
    if (name === 'AbortError' || name === 'TimeoutError') return true
  }
  if (error instanceof TypeError) return true
  if (error instanceof Error) {
    return /failed to fetch|networkerror|network request failed|load failed/i.test(error.message)
  }
  return false
}

/**
 * Чистое решение по результату `api.refresh()` при холодном старте.
 * Вынесено из компонента, чтобы покрыть тестом различение 401 и сетевой ошибки.
 */
export async function restoreSession(
  refresh: () => Promise<{ user: User }>,
  cachedUser: User | null,
): Promise<SessionRestore> {
  try {
    const data = await refresh()
    return { kind: 'authenticated', user: data.user, clearSession: false }
  } catch (error) {
    if (isUnauthorizedError(error)) return { kind: 'unauthenticated', clearSession: true }
    if (isNetworkError(error)) return { kind: 'offline', user: cachedUser, clearSession: false }
    // Прочие ответы сервера (5xx, 502 от прокси): сессию не сбрасываем,
    // показываем кэш, если он есть, — сеть может вернуться.
    return { kind: 'degraded', user: cachedUser, clearSession: false }
  }
}

/** Побочные эффекты применения результата восстановления (для тестов и компонента). */
export interface RestoreEffects {
  setUser: (user: User | null) => void
  persistUser: (user: User) => void
  clearCachedUser: () => void
  clearSessionHint: () => void
  setOffline: (offline: boolean) => void
  setAccessToken: (token: string | null) => void
}

/**
 * Единственное место, где решается судьба сессии по итогу старта:
 * 401 — чистим подсказку и кэш; сеть/сервер — сессию сохраняем.
 * Вынесено из эффекта, чтобы это поведение было покрыто тестом.
 */
export function applyRestoreResult(result: SessionRestore, effects: RestoreEffects): void {
  if (result.kind === 'authenticated') {
    effects.setUser(result.user)
    effects.persistUser(result.user)
    effects.setOffline(false)
    return
  }
  if (result.clearSession) {
    effects.setAccessToken(null)
    effects.clearSessionHint()
    effects.clearCachedUser()
    return
  }
  if (result.user) effects.setUser(result.user)
  effects.setOffline(result.kind === 'offline')
}

function storage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

function isUser(value: unknown): value is User {
  if (!value || typeof value !== 'object') return false
  const candidate = value as { id?: unknown; tab_no?: unknown; permissions?: unknown }
  return (
    typeof candidate.id === 'string' &&
    candidate.id.length > 0 &&
    typeof candidate.tab_no === 'string' &&
    Array.isArray(candidate.permissions)
  )
}

/** Прочитать кэш последнего пользователя (только профиль, без секретов). */
export function readCachedUser(): User | null {
  const store = storage()
  if (!store) return null
  try {
    const raw = store.getItem(LAST_USER_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    return isUser(parsed) ? parsed : null
  } catch {
    return null
  }
}

export function persistUser(user: User): void {
  const store = storage()
  if (!store) return
  try {
    store.setItem(LAST_USER_KEY, JSON.stringify(user))
  } catch {
    /* приватный режим или переполнение — офлайн-кэш не критичен */
  }
}

export function clearCachedUser(): void {
  try {
    storage()?.removeItem(LAST_USER_KEY)
  } catch {
    /* ignore */
  }
}

function hasSessionHint(): boolean {
  try {
    return storage()?.getItem(SESSION_HINT) === '1'
  } catch {
    return false
  }
}

function setSessionHint(): void {
  try {
    storage()?.setItem(SESSION_HINT, '1')
  } catch {
    /* ignore */
  }
}

function clearSessionHint(): void {
  try {
    storage()?.removeItem(SESSION_HINT)
  } catch {
    /* ignore */
  }
}

/**
 * Сообщение service worker'у: скоуп API-кэша по пользователю и очистка при выходе.
 * Без SW (или в тестах) молча ничего не делает.
 */
function notifyServiceWorker(message: Record<string, unknown>): void {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return
  const container = navigator.serviceWorker
  const send = (worker: ServiceWorker | null | undefined) => {
    try {
      worker?.postMessage(message)
    } catch {
      /* SW мог умереть — не мешаем выходу */
    }
  }
  if (container.controller) {
    send(container.controller)
    return
  }
  void container.ready.then((registration) => send(registration.active)).catch(() => undefined)
}

/** Плашка «офлайн»: показывается, когда сессия поднята из кэша без сети. */
export function OfflineBanner({ onDismiss }: { onDismiss?: () => void }) {
  return (
    <div
      data-testid="offline-banner"
      role="status"
      aria-live="polite"
      className="fixed inset-x-3 bottom-[calc(var(--bottom-nav)+12px)] z-[1400] flex items-start gap-2 rounded-xl border border-warm/40 bg-surface1/95 px-3 py-2 text-[13px] text-warm shadow-lg backdrop-blur md:inset-x-auto md:bottom-4 md:right-4 md:w-[380px]"
    >
      <span className="flex-1">
        <b>Офлайн.</b> Нет сети — показаны сохранённые данные. Изменения сохранятся на устройстве и
        уйдут при восстановлении связи.
      </span>
      {onDismiss ? (
        <button
          type="button"
          className="shrink-0 rounded px-1 text-[15px] leading-none text-warm/80 hover:text-warm"
          aria-label="Скрыть сообщение об офлайне"
          title="Скрыть"
          onClick={onDismiss}
        >
          ×
        </button>
      ) : null}
    </div>
  )
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [initializing, setInitializing] = useState(true)
  const [offline, setOffline] = useState(false)
  const [offlineBannerDismissed, setOfflineBannerDismissed] = useState(false)

  // Баннер можно свернуть, чтобы он не закрывал управление на карте.
  useEffect(() => {
    if (!offline) setOfflineBannerDismissed(false)
  }, [offline])

  // При старте пробуем восстановить сессию по httpOnly-cookie.
  const bootstrapped = useRef(false)
  useEffect(() => {
    if (bootstrapped.current) return
    bootstrapped.current = true

    if (!hasSessionHint()) {
      setInitializing(false)
      return
    }

    const cached = readCachedUser()
    void restoreSession(() => api.refresh(), cached)
      .then((result) =>
        applyRestoreResult(result, {
          setUser,
          persistUser,
          clearCachedUser,
          clearSessionHint,
          setOffline,
          setAccessToken,
        }),
      )
      .catch(() => {
        // restoreSession не бросает, но подстрахуемся, чтобы не остаться в Splash.
        setOffline(true)
      })
      .finally(() => setInitializing(false))
  }, [])

  // Баннер «офлайн» должен появляться и исчезать при живой смене сети.
  useEffect(() => {
    if (typeof window === 'undefined') return
    const onOnline = () => setOffline(false)
    const onOffline = () => setOffline(true)
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    if (typeof navigator !== 'undefined' && navigator.onLine === false) setOffline(true)
    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [])

  // Скоуп API-кэша service worker'а по текущему пользователю.
  const userId = user?.id ?? null
  useEffect(() => {
    if (!userId) return
    notifyServiceWorker({ type: 'karier-user', userId })
  }, [userId])

  const login = useCallback(async (tab_no: string, password: string) => {
    const data = await api.login(tab_no, password)
    if ('mfa_required' in data && data.mfa_required) {
      return data as MfaRequired
    }
    const pair = data as { user: User }
    setSessionHint()
    persistUser(pair.user)
    setUser(pair.user)
    setOffline(false)
    return null
  }, [])

  const verifyMfa = useCallback(async (challenge: string, code: string) => {
    const pair = await api.verifyMfa(challenge, code)
    setSessionHint()
    persistUser(pair.user)
    setUser(pair.user)
    setOffline(false)
  }, [])

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      // Нет сети — локальный выход важнее серверного отзыва: планшет общий.
    } finally {
      setAccessToken(null)
      clearSessionHint()
      clearCachedUser()
      notifyServiceWorker({ type: 'karier-clear-cache' })
      setUser(null)
      setOffline(false)
    }
  }, [])

  const refreshUser = useCallback(async () => {
    const fresh = await api.me()
    persistUser(fresh)
    setUser(fresh)
  }, [])

  const applyUser = useCallback((next: User) => {
    persistUser(next)
    setUser(next)
  }, [])

  const can = useCallback(
    (permission: string) => Boolean(user?.permissions?.includes(permission)),
    [user],
  )

  const value = useMemo(
    () => ({
      user,
      initializing,
      offline,
      login,
      verifyMfa,
      logout,
      refreshUser,
      applyUser,
      can,
    }),
    [user, initializing, offline, login, verifyMfa, logout, refreshUser, applyUser, can],
  )

  return (
    <AuthContext.Provider value={value}>
      {children}
      {offline && !offlineBannerDismissed ? (
        <OfflineBanner onDismiss={() => setOfflineBannerDismissed(true)} />
      ) : null}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('AuthProvider должен использоваться внутри AuthProvider')
  return context
}
