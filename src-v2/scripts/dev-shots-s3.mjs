/**
 * Скриншоты Спринта 3: карта, схема, карточка, реестр, справочник.
 * Запуск: node scripts/dev-shots-s3.mjs
 */

import { spawn } from 'node:child_process'
import { writeFileSync, mkdirSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9224
const BASE = 'http://127.0.0.1:5174'
const OUT_DIR = 'C:\\karier\\.tmp'
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile-s3'

mkdirSync(PROFILE, { recursive: true })

const browser = spawn(
  CHROME,
  [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE}`,
    '--no-first-run',
    '--disable-gpu',
    '--no-sandbox',
    '--hide-scrollbars',
    '--window-size=1440,900',
    'about:blank',
  ],
  { stdio: 'ignore' },
)

let ws
let nextId = 1
const pending = new Map()
const errors = []

function send(method, params = {}) {
  const id = nextId++
  ws.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id)
        reject(new Error(`timeout ${method}`))
      }
    }, 25000)
  })
}

async function evaluate(expression) {
  const result = await send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  })
  return result.result?.value
}

async function shot(name) {
  const data = await send('Page.captureScreenshot', { format: 'png' })
  const path = `${OUT_DIR}\\${name}.png`
  writeFileSync(path, Buffer.from(data.data, 'base64'))
  console.log('saved', path)
}

async function waitFor(expression, timeoutMs = 12000, label = '') {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const value = await evaluate(expression)
    if (value) return value
    await sleep(300)
  }
  console.log('waitFor timeout:', label || expression)
  return null
}

async function goto(path, waitMs = 2500) {
  await send('Page.navigate', { url: `${BASE}${path}` })
  await sleep(waitMs)
}

const clickByText = (text) => `(() => {
  const buttons = [...document.querySelectorAll('button')];
  const target = buttons.find(b => b.textContent.trim().includes(${JSON.stringify(text)}));
  if (!target) return 'not found: ' + ${JSON.stringify(text)};
  target.click();
  return 'clicked ' + ${JSON.stringify(text)};
})()`

async function main() {
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/version`)
      if (res.ok) break
    } catch {}
    await sleep(250)
  }

  const target = await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' }).then((r) => r.json())
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
    if (message.method === 'Runtime.exceptionThrown') {
      errors.push(message.params.exceptionDetails?.exception?.description ?? 'exception')
    }
    if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
      errors.push(message.params.args.map((a) => a.value ?? a.description).join(' '))
    }
  })

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })

  await goto('/login', 1500)
  await waitFor('document.querySelector("input") ? true : false', 15000, 'login form')
  const status = await evaluate(`fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({tab_no:'000001', password:'admin'}), credentials:'include'})
    .then(r => r.status + ' ' + r.statusText)`)
  console.log('login:', status)

  await goto('/', 2500)
  await waitFor('document.querySelectorAll(".karier-marker").length > 0', 15000, 'markers')
  console.log('url:', await evaluate('location.pathname'))
  console.log('markers:', await evaluate('document.querySelectorAll(".karier-marker").length'))
  await shot('s3-map')

  console.log(await evaluate(clickByText('Схема')))
  await sleep(3000)
  console.log('schema nodes:', await evaluate('document.querySelectorAll(".react-flow__node").length'))
  await shot('s3-schema')

  console.log(
    await evaluate(`(() => {
      const node = document.querySelectorAll('.react-flow__node')[6];
      if (!node) return 'no node';
      node.dispatchEvent(new MouseEvent('click', {bubbles: true}));
      return 'node clicked';
    })()`),
  )
  await sleep(2000)
  await shot('s3-schema-sheet')

  await goto('/registry', 2500)
  console.log('registry rows:', await evaluate('document.querySelectorAll("tbody tr").length'))
  await shot('s3-registry')

  await goto('/types', 2500)
  console.log('types rows:', await evaluate('document.querySelectorAll("tbody tr").length'))
  await shot('s3-types')

  await goto('/', 3000)
  await evaluate(`(() => {
    const marker = document.querySelectorAll('.karier-marker')[3];
    marker?.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    return marker ? 'marker' : 'none';
  })()`)
  await sleep(1800)
  console.log(await evaluate(clickByText('Документы')))
  await sleep(1200)
  await shot('s3-documents')

  console.log('errors:', errors.length ? errors.slice(0, 5) : 'none')
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
