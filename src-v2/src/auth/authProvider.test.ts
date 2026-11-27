import { afterEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { ApiError } from '../lib/api'
import type { User } from '../lib/api'
import {
  OfflineBanner,
  applyRestoreResult,
  clearCachedUser,
  isNetworkError,
  isUnauthorizedError,
  persistUser,
  readCachedUser,
  restoreSession,
} from './AuthProvider'
import type { RestoreEffects, SessionRestore } from './AuthProvider'

/** Проверяет вид результата и сужает тип для последующих assert'ов. */
function expectKind<K extends SessionRestore['kind']>(
  result: SessionRestore,
  kind: K,
): Extract<SessionRestore, { kind: K }> {
  expect(result.kind).toBe(kind)
  return result as Extract<SessionRestore, { kind: K }>
}

const cachedUser: User = {
  id: 'user-a',
  tab_no: '000001',
  full_name: 'Иванов Иван',
  position: 'Инженер',
  department: 'Энергоучасток',
  role: 'admin',
  permissions: ['asset.create', 'audit.view'],
  status: 'active',
  mfa_enabled: false,
  must_change_password: false,
  last_login_at: null,
}

function memoryStorage(): Storage {
  const data = new Map<string, string>()
  return {
    get length() {
      return data.size
    },
    clear: () => data.clear(),
    getItem: (key: string) => (data.has(key) ? data.get(key)! : null),
    key: (index: number) => Array.from(data.keys())[index] ?? null,
    removeItem: (key: string) => {
      data.delete(key)
    },
    setItem: (key: string, value: string) => {
      data.set(key, value)
    },
  } as Storage
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AuthProvider: различение 401 и сетевой ошибки', () => {
  it('явный 401 от сервера — сессии нет, её нужно очистить', async () => {
    const result = await restoreSession(
      () => Promise.reject(new ApiError(401, { detail: 'Сессия истекла' })),
      cachedUser,
    )

    expect(result.kind).toBe('unauthenticated')
    expect(result.clearSession).toBe(true)
    expect('user' in result).toBe(false)
  })

  it('TypeError сети — сессию не трогаем, поднимаем пользователя из кэша', async () => {
    const result = expectKind(
      await restoreSession(() => Promise.reject(new TypeError('Failed to fetch')), cachedUser),
      'offline',
    )

    expect(result.clearSession).toBe(false)
    expect(result.user?.id).toBe('user-a')
  })

  it('сетевая ошибка без кэша — всё равно offline и без сброса сессии', async () => {
    const result = expectKind(
      await restoreSession(() => Promise.reject(new TypeError('Failed to fetch')), null),
      'offline',
    )

    expect(result.clearSession).toBe(false)
    expect(result.user).toBeNull()
  })

  it('AbortError и Safari-сообщение «Load failed» тоже считаются сетевыми', async () => {
    const abort = Object.assign(new Error('The operation was aborted'), { name: 'AbortError' })
    const abortResult = await restoreSession(() => Promise.reject(abort), cachedUser)
    const safariResult = await restoreSession(
      () => Promise.reject(new TypeError('Load failed')),
      cachedUser,
    )

    expect(abortResult.kind).toBe('offline')
    expect(safariResult.kind).toBe('offline')
    expect(isNetworkError(abort)).toBe(true)
    expect(isNetworkError(new TypeError('Load failed'))).toBe(true)
  })

  it('5xx сервера — не повод разлогинивать: degraded + кэш', async () => {
    const result = expectKind(
      await restoreSession(
        () => Promise.reject(new ApiError(503, { detail: 'Сервис недоступен' })),
        cachedUser,
      ),
      'degraded',
    )

    expect(result.clearSession).toBe(false)
    expect(result.user?.id).toBe('user-a')
  })

  it('успешный refresh — authenticated, сессия сохраняется', async () => {
    const result = expectKind(
      await restoreSession(() => Promise.resolve({ user: cachedUser }), null),
      'authenticated',
    )

    expect(result.clearSession).toBe(false)
    expect(result.user.id).toBe('user-a')
  })

  it('предикаты: 401 — это не сетевая ошибка, TypeError — не 401', () => {
    expect(isUnauthorizedError(new ApiError(401, { detail: 'нет' }))).toBe(true)
    expect(isUnauthorizedError(new ApiError(500, { detail: 'нет' }))).toBe(false)
    expect(isUnauthorizedError(new TypeError('Failed to fetch'))).toBe(false)

    expect(isNetworkError(new TypeError('Failed to fetch'))).toBe(true)
    expect(isNetworkError(new ApiError(401, { detail: 'нет' }))).toBe(false)
    expect(isNetworkError(new ApiError(503, { detail: 'Сервис недоступен' }))).toBe(false)
  })
})

describe('AuthProvider: применение результата к сессии', () => {
  function effects() {
    const setUser = vi.fn()
    const persistUserSpy = vi.fn()
    const clearCachedUserSpy = vi.fn()
    const clearSessionHintSpy = vi.fn()
    const setOffline = vi.fn()
    const setAccessTokenSpy = vi.fn()
    const value: RestoreEffects = {
      setUser,
      persistUser: persistUserSpy,
      clearCachedUser: clearCachedUserSpy,
      clearSessionHint: clearSessionHintSpy,
      setOffline,
      setAccessToken: setAccessTokenSpy,
    }
    return {
      value,
      setUser,
      persistUser: persistUserSpy,
      clearCachedUser: clearCachedUserSpy,
      clearSessionHint: clearSessionHintSpy,
      setOffline,
      setAccessToken: setAccessTokenSpy,
    }
  }

  it('сеть недоступна: сессия и флаг karier-session сохранены, баннер включён', () => {
    const spies = effects()

    applyRestoreResult({ kind: 'offline', user: cachedUser, clearSession: false }, spies.value)

    expect(spies.setUser).toHaveBeenCalledWith(cachedUser)
    expect(spies.setOffline).toHaveBeenCalledWith(true)
    expect(spies.clearSessionHint).not.toHaveBeenCalled()
    expect(spies.clearCachedUser).not.toHaveBeenCalled()
    expect(spies.setAccessToken).not.toHaveBeenCalled()
  })

  it('401: сессия, кэш пользователя и токен очищены (уходим на /login)', () => {
    const spies = effects()

    applyRestoreResult({ kind: 'unauthenticated', clearSession: true }, spies.value)

    expect(spies.clearSessionHint).toHaveBeenCalledTimes(1)
    expect(spies.clearCachedUser).toHaveBeenCalledTimes(1)
    expect(spies.setAccessToken).toHaveBeenCalledWith(null)
    expect(spies.setUser).not.toHaveBeenCalled()
    expect(spies.setOffline).not.toHaveBeenCalled()
  })

  it('успешный refresh: пользователь сохранён в кэш, офлайн-баннер выключен', () => {
    const spies = effects()

    applyRestoreResult(
      { kind: 'authenticated', user: cachedUser, clearSession: false },
      spies.value,
    )

    expect(spies.setUser).toHaveBeenCalledWith(cachedUser)
    expect(spies.persistUser).toHaveBeenCalledWith(cachedUser)
    expect(spies.setOffline).toHaveBeenCalledWith(false)
    expect(spies.clearSessionHint).not.toHaveBeenCalled()
  })
})

describe('AuthProvider: баннер офлайна', () => {
  it('содержит слово «Офлайн», пояснение и role=status', () => {
    const markup = renderToStaticMarkup(
      createElement(OfflineBanner, { onDismiss: () => undefined }),
    )

    expect(markup).toContain('role="status"')
    expect(markup).toContain('aria-live="polite"')
    expect(markup).toContain('Офлайн')
    expect(markup).toContain('Нет сети')
    expect(markup).toContain('Скрыть сообщение об офлайне')
  })
})

describe('AuthProvider: кэш последнего пользователя', () => {
  it('сохраняет и читает профиль, не трогая секреты', () => {
    vi.stubGlobal('localStorage', memoryStorage())

    persistUser(cachedUser)

    const stored = localStorage.getItem('karier-last-user') ?? ''
    expect(stored).toContain('user-a')
    expect(stored).not.toContain('token')

    const restored = readCachedUser()
    expect(restored?.tab_no).toBe('000001')
    expect(restored?.permissions).toEqual(['asset.create', 'audit.view'])
  })

  it('после выхода кэш пуст', () => {
    vi.stubGlobal('localStorage', memoryStorage())

    persistUser(cachedUser)
    clearCachedUser()

    expect(localStorage.getItem('karier-last-user')).toBeNull()
    expect(readCachedUser()).toBeNull()
  })

  it('битый или чужой JSON не роняет старт', () => {
    vi.stubGlobal('localStorage', memoryStorage())
    localStorage.setItem('karier-last-user', '{"id":')

    expect(readCachedUser()).toBeNull()

    localStorage.setItem('karier-last-user', JSON.stringify({ id: 'x' }))
    expect(readCachedUser()).toBeNull()
  })
})
