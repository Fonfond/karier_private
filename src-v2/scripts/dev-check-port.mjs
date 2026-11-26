/** Точечная проверка: позиция конкретного порта до и после перетаскивания. */

import { spawn } from 'node:child_process'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9334
const BASE = 'http://127.0.0.1:5174'
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile-s9c'

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

async function waitFor(expression, timeoutMs = 15000) {
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
  await sleep(3200)
  await evaluate(`(() => {
    const tab = [...document.querySelectorAll('button')].find((node) => node.textContent.trim() === 'Схема');
    tab?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return Boolean(tab);
  })()`)
  await sleep(2500)

  for (const labelText of ['Режим редактирования', 'Двигать порты']) {
    await evaluate(`(() => {
      const label = [...document.querySelectorAll('label')].find((node) => node.textContent.includes(${JSON.stringify(labelText)}));
      label?.querySelector('input')?.click();
      return Boolean(label);
    })()`)
    await sleep(1000)
  }

  const info = await evaluate(`(() => {
    const nodes = [...document.querySelectorAll('.react-flow__node')];
    for (const node of nodes) {
      const handles = [...node.querySelectorAll('.react-flow__handle')];
      const handle = handles.find((item) => {
        const rect = item.getBoundingClientRect();
        return rect.width > 0 && rect.top > 250 && rect.left > 300;
      });
      if (handle) {
        const rect = handle.getBoundingClientRect();
        return {
          nodeId: handle.getAttribute('data-nodeid'),
          handleId: handle.getAttribute('data-handleid'),
          x: rect.x + rect.width / 2,
          y: rect.y + rect.height / 2,
        };
      }
    }
    return null;
  })()`)
  console.log('handle:', info && { node: info.nodeId, port: info.handleId })

  if (!info) return

  const readPort = async (nodeId, handleId) => {
    return evaluate(`(() => {
      const all = [...document.querySelectorAll('.react-flow__handle')];
      const target = all.find((item) => item.getAttribute('data-handleid') === ${JSON.stringify(handleId)});
      return target ? { left: target.style.left, top: target.style.top } : null;
    })()`)
  }

  const before = await readPort(info.nodeId, info.handleId)
  console.log('before:', before)

  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: info.x, y: info.y, button: 'left', clickCount: 1 })
  for (let step = 1; step <= 8; step++) {
    await send('Input.dispatchMouseEvent', {
      type: 'mouseMoved',
      x: info.x - (70 * step) / 8,
      y: info.y + (45 * step) / 8,
      button: 'left',
    })
    await sleep(60)
  }
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: info.x - 70, y: info.y + 45, button: 'left' })
  await sleep(700)

  await evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find((node) => node.textContent.includes('Сохранить раскладку'));
    button?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return Boolean(button);
  })()`)
  await sleep(2500)
  await waitFor(`!document.body.innerText.includes('Сохраняем…')`)

  const after = await readPort(info.nodeId, info.handleId)
  console.log('after:', after)
  console.log('changed:', JSON.stringify(before) !== JSON.stringify(after))
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
