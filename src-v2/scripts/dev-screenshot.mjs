/**
 * Скриншот интерфейса через Chrome DevTools Protocol.
 * Нужен для проверки карты без установки Playwright.
 *
 * Запуск:  node scripts/dev-screenshot.mjs [url] [out.png]
 * Требует запущенных Vite (5174) и API (8001).
 */

import { spawn } from 'node:child_process'
import { writeFileSync, mkdirSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9223
const START_URL = process.argv[2] ?? 'http://127.0.0.1:5174/'
const OUT = process.argv[3] ?? 'C:\\karier\\.tmp\\screen.png'
const WIDTH = Number(process.argv[4] ?? 1280)
const HEIGHT = Number(process.argv[5] ?? 900)
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile'

mkdirSync(PROFILE, { recursive: true })

const browser = spawn(
  CHROME,
  [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--hide-scrollbars',
    '--force-device-scale-factor=1',
    '--window-size=' + WIDTH + ',' + HEIGHT,
    'about:blank',
  ],
  { stdio: 'ignore', detached: false },
)

let ws
let nextId = 1
const pending = new Map()
const consoleErrors = []

function send(method, params = {}) {
  const id = nextId++
  ws.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id)
        reject(new Error(`timeout: ${method}`))
      }
    }, 20000)
  })
}

async function waitForDevtools() {
  for (let i = 0; i < 60; i++) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/json/version`)
      if (response.ok) return
    } catch {
      // ещё не поднялся
    }
    await sleep(250)
  }
  throw new Error('Chrome DevTools не отвечает')
}

async function main() {
  await waitForDevtools()

  const target = await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent('about:blank')}`, {
    method: 'PUT',
  }).then((r) => r.json())

  ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true })
    ws.addEventListener('error', reject, { once: true })
  })

  ws.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    if (message.id && pending.has(message.id)) {
      const { resolve, reject } = pending.get(message.id)
      pending.delete(message.id)
      if (message.error) reject(new Error(JSON.stringify(message.error)))
      else resolve(message.result)
      return
    }
    if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
      consoleErrors.push(message.params.args.map((a) => a.value ?? a.description).join(' '))
    }
    if (message.method === 'Runtime.exceptionThrown') {
      consoleErrors.push(message.params.exceptionDetails?.exception?.description ?? 'exception')
    }
  })

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride', {
    width: WIDTH,
    height: HEIGHT,
    deviceScaleFactor: 1,
    mobile: WIDTH < 600,
  })

  await send('Page.navigate', { url: 'http://127.0.0.1:5174/login' })
  await sleep(2500)

  // вход через тот же origin: refresh-cookie останется в профиле браузера
  const login = await send('Runtime.evaluate', {
    expression: `fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({tab_no:'000001', password:'admin'}), credentials:'include'})
      .then(r => r.status)`,
    awaitPromise: true,
    returnByValue: true,
  })
  console.log('login status:', login.result?.value)

  await send('Page.navigate', { url: START_URL })
  await sleep(4000)

  const title = await send('Runtime.evaluate', {
    expression: 'document.title + " | " + document.querySelectorAll("h1,h2").length',
    returnByValue: true,
  })
  console.log('page:', title.result?.value)

  const markers = await send('Runtime.evaluate', {
    expression: 'document.querySelectorAll(".karier-marker").length',
    returnByValue: true,
  })
  console.log('markers:', markers.result?.value)

  const shot = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(OUT, Buffer.from(shot.data, 'base64'))
  console.log('saved:', OUT)

  // второй кадр: открываем карточку объекта (bottom sheet)
  const clicked = await send('Runtime.evaluate', {
    expression: `(() => {
      const markers = document.querySelectorAll('.karier-marker');
      if (!markers.length) return 'no markers';
      markers[Math.min(3, markers.length - 1)].dispatchEvent(new MouseEvent('click', {bubbles: true}));
      return 'clicked ' + markers.length;
    })()`,
    returnByValue: true,
  })
  console.log('sheet:', clicked.result?.value)
  await sleep(1500)

  const sheet = await send('Page.captureScreenshot', { format: 'png' })
  const sheetPath = OUT.replace(/\.png$/, '-sheet.png')
  writeFileSync(sheetPath, Buffer.from(sheet.data, 'base64'))
  console.log('saved:', sheetPath)

  if (consoleErrors.length) {
    console.log('console errors:', JSON.stringify(consoleErrors.slice(0, 5), null, 2))
  } else {
    console.log('console errors: none')
  }
}

try {
  await main()
} catch (error) {
  console.error('FAILED:', error.message)
  process.exitCode = 1
} finally {
  try {
    ws?.close()
  } catch {}
  browser.kill()
}
