/* Service Worker: оболочка приложения и GET-API кэш, скоупленный по пользователю.
 *
 * Правила:
 *  - имена кэшей содержат build-id сборки (выводится из /index.html), поэтому
 *    после деплоя старые кэши удаляются в activate;
 *  - API-кэш отдельный для каждого user.id: данные одного сотрудника не видны
 *    другому на общем планшете;
 *  - записи API живут не дольше 5 минут и ограничены по количеству;
 *  - при выходе приложение присылает 'karier-clear-cache' — кэши удаляются.
 */

const VERSION = 'karier-v3'
const BUILD_ID_FALLBACK = 'dev'
const SHELL_URLS = ['/', '/index.html']

const META_CACHE = 'karier-sw-meta'
const META_USER_URL = '/__karier_sw_user'
const API_TTL_MS = 5 * 60 * 1000
const API_MAX_ENTRIES = 100
const CACHED_AT_HEADER = 'x-karier-cached-at'

/** undefined — ещё не спрашивали, null — пользователя нет. */
let currentUserId
let buildIdPromise = null
let metaCachePromise = null

function hashId(value) {
  let hash = 5381
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 33) ^ value.charCodeAt(index)
  }
  return (hash >>> 0).toString(36)
}

/** build-id: имя хэшированного entry-чанка из собранного index.html. */
function fetchBuildId() {
  if (!buildIdPromise) {
    buildIdPromise = (async () => {
      try {
        const response = await fetch('/index.html', { cache: 'no-store' })
        if (!response.ok) return BUILD_ID_FALLBACK
        const html = await response.text()
        const match = html.match(/\/assets\/([^"']+\.js)/)
        return match ? hashId(match[1]) : BUILD_ID_FALLBACK
      } catch {
        return BUILD_ID_FALLBACK
      }
    })()
  }
  return buildIdPromise
}

function shellCacheName(buildId) {
  return `${VERSION}-${buildId}-shell`
}

function apiCacheName(buildId, userId) {
  return `${VERSION}-${buildId}-api-${userId}`
}

function metaRequest() {
  return new URL(META_USER_URL, self.location.origin).href
}

function openMetaCache() {
  if (!metaCachePromise) metaCachePromise = caches.open(META_CACHE)
  return metaCachePromise
}

async function persistUserId(userId) {
  try {
    const cache = await openMetaCache()
    await cache.put(
      metaRequest(),
      new Response(JSON.stringify({ userId }), {
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  } catch {
    /* приватный режим / квота — просто не запоминаем пользователя между стартами */
  }
}

async function readPersistedUserId() {
  try {
    const cache = await openMetaCache()
    const response = await cache.match(metaRequest())
    if (!response) return null
    const data = await response.json()
    return typeof data?.userId === 'string' && data.userId ? data.userId : null
  } catch {
    return null
  }
}

async function resolveUserId() {
  if (currentUserId !== undefined) return currentUserId
  currentUserId = await readPersistedUserId()
  return currentUserId
}

async function acceptUserId(userId) {
  currentUserId = userId
  await persistUserId(userId)
}

/** Выход: сносим API-кэши всех пользователей и метку текущего. */
async function clearUserCaches() {
  currentUserId = null
  try {
    const keys = await caches.keys()
    await Promise.all(
      keys.filter((name) => name.includes('-api-')).map((name) => caches.delete(name)),
    )
  } catch {
    /* кэш уже пуст */
  }
  try {
    const cache = await openMetaCache()
    await cache.delete(metaRequest())
  } catch {
    /* ignore */
  }
  try {
    await caches.delete(META_CACHE)
  } catch {
    /* ignore */
  }
  metaCachePromise = null
}

function isApiGet(request, url) {
  return request.method === 'GET' && url.pathname.startsWith('/api/')
}

function isPrivateApi(url) {
  return (
    url.pathname.startsWith('/api/auth') ||
    url.pathname.startsWith('/api/sync') ||
    url.pathname.startsWith('/api/media') ||
    url.pathname.startsWith('/api/documents') ||
    url.pathname.startsWith('/api/map/layers/')
  )
}

function isDevAsset(url) {
  return (
    url.pathname.startsWith('/src/') ||
    url.pathname.startsWith('/@') ||
    url.pathname.startsWith('/node_modules/')
  )
}

function isCacheableAsset(url) {
  return (
    url.pathname.startsWith('/assets/') ||
    /\.(js|css|png|jpe?g|webp|svg|ico|woff2?)$/i.test(url.pathname)
  )
}

/** Кэшируем только успешный JSON, который сервер явно разрешил кэшировать. */
function shouldCacheResponse(response) {
  if (!response || !response.ok) return false
  const cacheControl = (response.headers.get('Cache-Control') || '').toLowerCase()
  if (cacheControl.includes('no-store') || cacheControl.includes('private')) return false
  const contentType = (response.headers.get('Content-Type') || '').toLowerCase()
  if (!contentType.includes('application/json')) return false
  const length = Number(response.headers.get('Content-Length') || 0)
  if (Number.isFinite(length) && length > 512 * 1024) return false
  return true
}

async function trimApiCache(cache) {
  try {
    const keys = await cache.keys()
    let extra = keys.length - API_MAX_ENTRIES
    for (const key of keys) {
      if (extra <= 0) break
      await cache.delete(key)
      extra -= 1
    }
  } catch {
    /* ignore */
  }
}

async function cacheApiResponse(request, response) {
  const userId = await resolveUserId()
  if (!userId) return
  if (!shouldCacheResponse(response)) return
  const buildId = await fetchBuildId()
  const headers = new Headers(response.headers)
  headers.set(CACHED_AT_HEADER, String(Date.now()))
  const body = await response.arrayBuffer()
  const cache = await caches.open(apiCacheName(buildId, userId))
  await cache.put(
    request,
    new Response(body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    }),
  )
  await trimApiCache(cache)
}

async function readApiResponse(request) {
  const userId = await resolveUserId()
  if (!userId) return null
  const buildId = await fetchBuildId()
  const cache = await caches.open(apiCacheName(buildId, userId))
  const cached = await cache.match(request)
  if (!cached) return null
  const cachedAt = Number(cached.headers.get(CACHED_AT_HEADER) || 0)
  if (!cachedAt || Date.now() - cachedAt > API_TTL_MS) {
    await cache.delete(request)
    return null
  }
  return cached
}

function offlineApiResponse() {
  return new Response(
    JSON.stringify({ detail: 'Нет сети, данные недоступны', code: 'offline' }),
    {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    },
  )
}

async function handleApiRequest(request) {
  try {
    const response = await fetch(request)
    if (response.ok) {
      const copy = response.clone()
      try {
        await cacheApiResponse(request, copy)
      } catch {
        /* не смогли закэшировать — ответ всё равно отдаём */
      }
    }
    return response
  } catch {
    try {
      const cached = await readApiResponse(request)
      if (cached) return cached
    } catch {
      /* кэш недоступен */
    }
    return offlineApiResponse()
  }
}

async function handleNavigation(request) {
  try {
    return await fetch(request)
  } catch {
    const buildId = await fetchBuildId()
    const cache = await caches.open(shellCacheName(buildId))
    const cached = (await cache.match('/index.html')) || (await cache.match('/'))
    if (cached) return cached
    return new Response('Нет сети, оболочка приложения не закэширована', {
      status: 503,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    })
  }
}

async function handleAsset(request, url) {
  const buildId = await fetchBuildId()
  const cache = await caches.open(shellCacheName(buildId))
  const cached = await cache.match(request)
  if (cached) return cached
  try {
    const response = await fetch(request)
    if (response.ok && isCacheableAsset(url)) {
      try {
        await cache.put(request, response.clone())
      } catch {
        /* ignore */
      }
    }
    return response
  } catch {
    return new Response('', { status: 504 })
  }
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const buildId = await fetchBuildId()
      try {
        const cache = await caches.open(shellCacheName(buildId))
        await cache.addAll(SHELL_URLS)
      } catch {
        /* сеть недоступна при установке — оболочка догрузится при первом онлайне */
      }
      await self.skipWaiting()
    })(),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const buildId = await fetchBuildId()
      const keepPrefix = `${VERSION}-${buildId}`
      try {
        const keys = await caches.keys()
        await Promise.all(
          keys
            .filter((name) => name !== META_CACHE && !name.startsWith(keepPrefix))
            .map((name) => caches.delete(name)),
        )
      } catch {
        /* ignore */
      }
      await self.clients.claim()
    })(),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (isDevAsset(url)) return
  if (isPrivateApi(url)) return

  if (isApiGet(request, url)) {
    event.respondWith(handleApiRequest(request))
    return
  }

  if (request.mode === 'navigate') {
    event.respondWith(handleNavigation(request))
    return
  }

  event.respondWith(handleAsset(request, url))
})

self.addEventListener('sync', (event) => {
  if (event.tag !== 'karier-outbox') return
  event.waitUntil(
    self.clients.matchAll({ includeUncontrolled: true }).then((clients) => {
      clients.forEach((client) => client.postMessage({ type: 'karier-sync-request' }))
    }),
  )
})

self.addEventListener('message', (event) => {
  const data = event.data
  if (!data || typeof data !== 'object') return

  const keepAlive = (promise) => {
    try {
      event.waitUntil(promise)
    } catch {
      void promise
    }
  }

  if (data.type === 'karier-skip-waiting') {
    self.skipWaiting()
    return
  }
  if (data.type === 'karier-user' && typeof data.userId === 'string' && data.userId) {
    keepAlive(acceptUserId(data.userId))
    return
  }
  if (data.type === 'karier-clear-cache') {
    keepAlive(clearUserCaches())
  }
})
