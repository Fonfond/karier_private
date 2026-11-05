/* Service Worker: оболочка, подложка карты и кэш GET-API для работы без сети. */

const VERSION = 'karier-v2'
const SHELL_CACHE = `${VERSION}-shell`
const API_CACHE = `${VERSION}-api`
const SHELL_URLS = ['/', '/index.html', '/karier-map.jpg']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_URLS))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => !key.startsWith(VERSION)).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  )
})

function isApiGet(request, url) {
  return request.method === 'GET' && url.pathname.startsWith('/api/')
}

function isPrivateApi(url) {
  return (
    url.pathname.startsWith('/api/auth') ||
    url.pathname.startsWith('/api/sync') ||
    url.pathname.startsWith('/api/media') ||
    url.pathname.startsWith('/api/documents')
  )
}

function isDevAsset(url) {
  return (
    url.pathname.startsWith('/src/') ||
    url.pathname.startsWith('/@') ||
    url.pathname.startsWith('/node_modules/')
  )
}

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (isDevAsset(url)) return
  if (isPrivateApi(url)) return

  if (isApiGet(request, url)) {
    // сеть в приоритете, при офлайне — последняя удачная копия
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone()
          caches.open(API_CACHE).then((cache) => cache.put(request, copy))
          return response
        })
        .catch(() =>
          caches.match(request).then(
            (cached) =>
              cached ||
              new Response(JSON.stringify({ detail: 'Нет сети, данные недоступны', code: 'offline' }), {
                status: 503,
                headers: { 'Content-Type': 'application/json' },
              }),
          ),
        ),
    )
    return
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() => caches.match('/index.html').then((cached) => cached || caches.match('/'))),
    )
    return
  }

  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).then((response) => {
          if (response.ok && (url.pathname.endsWith('.jpg') || url.pathname.endsWith('.png') || url.pathname.endsWith('.js') || url.pathname.endsWith('.css') || url.pathname.endsWith('.svg'))) {
            const copy = response.clone()
            caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy))
          }
          return response
        }),
    ),
  )
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
  if (event.data?.type === 'karier-skip-waiting') self.skipWaiting()
})
