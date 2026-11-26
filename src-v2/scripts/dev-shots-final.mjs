/** Финальные скриншоты: тур, режим презентации, удаление дефектов. */

import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9336
const BASE = 'http://127.0.0.1:5174'
const OUT = 'C:\\karier\\.tmp'
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile-final'

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
    '--window-size=1440,1000',
    'about:blank',
  ],
  { stdio: 'ignore' },
)

let ws
let nextId = 1
const pending = new Map()
const errors = []

const send = (method, params = {}) => {
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

const evaluate = async (expression) => {
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
  return result.result?.value
}

const shot = async (name) => {
  const data = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(`${OUT}\\${name}.png`, Buffer.from(data.data, 'base64'))
  console.log('saved', name)
}

const waitFor = async (expression, timeoutMs = 15000) => {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (await evaluate(expression)) return true
    await sleep(300)
  }
  return false
}

const clickText = (text) =>
  evaluate(`(() => {
    const nodes = [...document.querySelectorAll('button, label, a')];
    const target = nodes.find((node) => node.textContent.trim().includes(${JSON.stringify(text)}));
    if (!target) return false;
    target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return true;
  })()`)

async function main() {
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(`http://127.0.0.1:${PORT}/json/version`)).ok) break
    } catch {}
    await sleep(250)
  }

  const target = await fetch(`http://127.0.0.1:${PORT}/json/new`, { method: 'PUT' }).then((r) => r.json())
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
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })

  await send('Page.navigate', { url: `${BASE}/login` })
  await sleep(2000)
  await evaluate(
    `fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({tab_no:'000001',password:'admin'}),credentials:'include'}).then(r=>r.status)`,
  )

  // тур
  await send('Page.navigate', { url: `${BASE}/` })
  await sleep(3200)
  await waitFor(`document.body.innerText.includes('Знакомство')`)
  await shot('s10-tour')

  await clickText('Пропустить')
  await sleep(600)
  console.log('tour closed:', !(await evaluate(`document.body.innerText.includes('Знакомство')`)))

  // режим презентации
  await evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find((node) => node.textContent.trim() === '🎬');
    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return Boolean(button);
  })()`)
  await sleep(1200)
  console.log('zoom:', await evaluate(`getComputedStyle(document.documentElement).zoom`))
  await shot('s10-presentation')

  await evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find((node) => node.textContent.trim() === '🎬');
    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return Boolean(button);
  })()`)
  await sleep(600)

  // удаление дефекта
  await send('Page.navigate', { url: `${BASE}/defects` })
  await sleep(2800)
  await waitFor(`document.body.innerText.includes('Дефекты')`)
  console.log('delete buttons:', await evaluate(`[...document.querySelectorAll('button')].filter((b) => b.textContent.includes('Удалить')).length`))
  await shot('s10-defects')

  console.log('errors:', errors.length ? errors.slice(0, 3) : 'none')
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
