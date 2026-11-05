/** Проверка перетаскивания порта и чистые скриншоты Спринта 9. */

import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9333
const BASE = 'http://127.0.0.1:5174'
const OUT = 'C:\\karier\\.tmp'
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile-s9b'

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

  await send('Page.navigate', { url: `${BASE}/map` })
  await sleep(3200)
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
  await sleep(1000)
  await evaluate(`(() => {
    const label = [...document.querySelectorAll('label')].find((node) => node.textContent.includes('Двигать порты'));
    label?.querySelector('input')?.click();
    return Boolean(label);
  })()`)
  await sleep(1500)
  await shot('s9-schema-ports')

  const handle = await evaluate(`(() => {
    const nodes = [...document.querySelectorAll('.react-flow__node')];
    for (const node of nodes) {
      const handles = [...node.querySelectorAll('.react-flow__handle')];
      const target = handles.find((item) => {
        const rect = item.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && rect.top > 200;
      });
      if (target) {
        const rect = target.getBoundingClientRect();
        return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
      }
    }
    return null;
  })()`)
  console.log('handle:', handle && { x: Math.round(handle.x), y: Math.round(handle.y) })

  if (handle) {
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: handle.x, y: handle.y, button: 'left', clickCount: 1 })
    for (let step = 1; step <= 5; step++) {
      await send('Input.dispatchMouseEvent', {
        type: 'mouseMoved',
        x: handle.x + (30 * step) / 5,
        y: handle.y + (40 * step) / 5,
        button: 'left',
      })
      await sleep(70)
    }
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: handle.x + 30, y: handle.y + 40, button: 'left' })
    await sleep(700)
  }

  const enabled = await evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find((node) => node.textContent.includes('Сохранить раскладку'));
    return button ? !button.disabled : null;
  })()`)
  console.log('save enabled after port drag:', enabled)

  await evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find((node) => node.textContent.includes('Сохранить раскладку'));
    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return Boolean(button);
  })()`)
  await sleep(2200)

  const status = await evaluate(`(() => {
    const text = document.body.innerText;
    const match = text.match(/узлов\\s+\\d+,\\s+портов\\s+\\d+/);
    return match ? match[0] : null;
  })()`)
  console.log('status:', status)
  await shot('s9-schema-ports-saved')

  console.log('errors:', errors.length ? errors.slice(0, 4) : 'none')
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
