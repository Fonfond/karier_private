/** Скриншоты Спринта 4: обход, дефекты, QR. */

import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9225
const BASE = 'http://127.0.0.1:5174'
const OUT_DIR = 'C:\\karier\\.tmp'
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile-s4'

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
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  return result.result?.value
}

async function shot(name) {
  const data = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(`${OUT_DIR}\\${name}.png`, Buffer.from(data.data, 'base64'))
  console.log('saved', name)
}

async function waitFor(expression, timeoutMs = 12000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (await evaluate(expression)) return true
    await sleep(300)
  }
  return false
}

async function goto(path, wait = 2200) {
  await send('Page.navigate', { url: `${BASE}${path}` })
  await sleep(wait)
}

const clickText = (text) => `(() => {
  const btn = [...document.querySelectorAll('button')].find(b => b.textContent.includes(${JSON.stringify(text)}));
  if (!btn) return 'not found: ' + ${JSON.stringify(text)};
  btn.click();
  return 'clicked';
})()`

async function main() {
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(`http://127.0.0.1:${PORT}/json/version`)).ok) break
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
  })

  await send('Page.enable')
  await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })

  await goto('/login', 1500)
  await waitFor('Boolean(document.querySelector("input"))', 15000)
  console.log('login:', await evaluate(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({tab_no:'000001',password:'admin'}),credentials:'include'}).then(r=>r.status)`))

  await goto('/inspections', 2500)
  await waitFor('document.body.innerText.includes("Обход")', 12000)
  await shot('s4-inspection-start')

  console.log(await evaluate(clickText('Начать обход')))
  await sleep(3000)
  await shot('s4-inspection-list')

  console.log(await evaluate(clickText('Норма')))
  await sleep(1500)
  await shot('s4-inspection-marked')

  await goto('/defects', 2500)
  await shot('s4-defects')

  await goto('/', 3000)
  await waitFor('document.querySelectorAll(".karier-marker").length > 0', 12000)
  await evaluate(`document.querySelectorAll('.karier-marker')[5]?.dispatchEvent(new MouseEvent('click',{bubbles:true}))`)
  await sleep(1800)
  const qr = await evaluate(`(() => {
    const btn = document.querySelector('button[title="QR-код объекта"]');
    if (!btn) return 'qr button not found';
    btn.click(); return 'qr opened';
  })()`)
  console.log(qr)
  await sleep(1200)
  await shot('s4-qr')

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
