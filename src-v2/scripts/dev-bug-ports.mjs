/** Воспроизведение бага: включение режима «Двигать порты». */

import { spawn } from 'node:child_process'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9335
const BASE = 'http://127.0.0.1:5174'
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile-bug'

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
const logs = []

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
    if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
      logs.push(message.params.args.map((arg) => arg.value ?? arg.description ?? '').join(' '))
    }
    if (message.method === 'Runtime.exceptionThrown') {
      logs.push('EXCEPTION: ' + (message.params.exceptionDetails?.exception?.description ?? 'unknown'))
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

  const count = () =>
    evaluate(`document.querySelectorAll('.react-flow__node').length`)

  console.log('nodes before edit:', await count())

  await evaluate(`(() => {
    const label = [...document.querySelectorAll('label')].find((node) => node.textContent.includes('Режим редактирования'));
    label?.querySelector('input')?.click();
    return Boolean(label);
  })()`)
  await sleep(1200)
  console.log('nodes after edit mode:', await count())

  await evaluate(`(() => {
    const label = [...document.querySelectorAll('label')].find((node) => node.textContent.includes('Двигать порты'));
    label?.querySelector('input')?.click();
    return Boolean(label);
  })()`)
  await sleep(1800)
  console.log('nodes after port mode:', await count())
  console.log('port handles:', await evaluate(`document.querySelectorAll('.react-flow__handle').length`))
  console.log('body text sample:', (await evaluate('document.body.innerText')).slice(0, 120).replace(/\n/g, ' | '))
  console.log('errors:', logs.length, String(logs[0] ?? '').slice(0, 400).replace(/\n/g, ' '))
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
