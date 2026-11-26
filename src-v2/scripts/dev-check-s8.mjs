/** Проверка ручного редактора: перетаскивание узла и сохранение раскладки. */

import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9331
const BASE = 'http://127.0.0.1:5174'
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile-s8drag'

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

const waitFor = async (expression, timeoutMs = 15000) => {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (await evaluate(expression)) return true
    await sleep(300)
  }
  return false
}

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

  await send('Page.navigate', { url: `${BASE}/map` })
  await sleep(3000)
  await evaluate(`(() => {
    const tab = [...document.querySelectorAll('button')].find((node) => node.textContent.trim() === 'Схема');
    tab?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return Boolean(tab);
  })()`)
  await sleep(2500)

  await evaluate(`(() => {
    const label = [...document.querySelectorAll('label')].find((node) => node.textContent.includes('Режим редактирования'));
    label?.querySelector('input')?.click();
    return Boolean(label);
  })()`)
  await sleep(1200)

  const box = await evaluate(`(() => {
    const nodes = [...document.querySelectorAll('.react-flow__node')];
    const node = nodes.find((item) => item.getBoundingClientRect().width > 100);
    if (!node) return null;
    const rect = node.getBoundingClientRect();
    return { id: node.getAttribute('data-id'), x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
  })()`)
  console.log('node:', box?.id, box && Math.round(box.x), box && Math.round(box.y))

  if (box) {
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x, y: box.y, button: 'left', clickCount: 1 })
    for (let step = 1; step <= 6; step++) {
      await send('Input.dispatchMouseEvent', {
        type: 'mouseMoved',
        x: box.x + (140 * step) / 6,
        y: box.y - (110 * step) / 6,
        button: 'left',
      })
      await sleep(60)
    }
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box.x + 140, y: box.y - 110, button: 'left' })
    await sleep(800)
  }

  const enabled = await evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find((node) => node.textContent.includes('Сохранить раскладку'));
    return button ? !button.disabled : null;
  })()`)
  console.log('save button enabled after drag:', enabled)

  await evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find((node) => node.textContent.includes('Сохранить раскладку'));
    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return Boolean(button);
  })()`)
  await sleep(1800)

  const status = await evaluate(`document.body.innerText.match(/Ручная раскладка[^\\n]*/)?.[0] ?? null`)
  console.log('status:', status)

  const shot = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync('C:\\karier\\.tmp\\s8-schema-dragged.png', Buffer.from(shot.data, 'base64'))

  const saved = await evaluate(
    `fetch('/api/topology/graph', { headers: { Authorization: 'Bearer ' + '' } }).then(r => r.status).catch(() => 0)`,
  )
  console.log('graph fetch status (без токена ожидаем 401/403):', saved)
  console.log('node id:', box?.id)
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
