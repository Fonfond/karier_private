/** Финальные скриншоты после аудита (после исправлений). */

import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9347
const BASE = 'http://127.0.0.1:5174'
const OUT = 'C:\\karier\\.tmp'
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile-s14'
const browser = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${PROFILE}`, '--no-first-run', '--disable-gpu', '--no-sandbox',
  '--hide-scrollbars', '--window-size=393,851', 'about:blank'], { stdio: 'ignore' })

let ws, nextId = 1
const pending = new Map()
const errors = []
const send = (method, params = {}) => {
  const id = nextId++
  ws.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject })
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error('timeout ' + method)) } }, 25000)
  })
}
const ev = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
  return r.result?.value
}
const shot = async (name) => {
  const data = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(`${OUT}\\${name}.png`, Buffer.from(data.data, 'base64'))
  console.log('saved', name)
}
const click = (text) => ev(`(() => {
  const n = [...document.querySelectorAll('button, a')].find(x => x.textContent.trim().includes(${JSON.stringify(text)}));
  if (!n) return false; n.dispatchEvent(new MouseEvent('click', { bubbles: true })); return true;
})()`)

async function main() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`http://127.0.0.1:${PORT}/json/version`)).ok) break } catch {}
    await sleep(250)
  }
  const target = await fetch(`http://127.0.0.1:${PORT}/json/new`, { method: 'PUT' }).then(r => r.json())
  ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((res, rej) => { ws.addEventListener('open', res, { once: true }); ws.addEventListener('error', rej, { once: true }) })
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data)
    if (m.id && pending.has(m.id)) { const { resolve, reject } = pending.get(m.id); pending.delete(m.id); m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result); return }
    if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails?.exception?.description ?? 'exception')
  })
  await send('Page.enable'); await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: 393, height: 851, deviceScaleFactor: 3, mobile: true, screenWidth: 393, screenHeight: 851 })
  await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 })

  await send('Page.navigate', { url: `${BASE}/login` }); await sleep(2000)
  await ev(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tab_no:'000001',password:'admin'}),credentials:'include'}).then(r=>r.status)`)
  await send('Page.navigate', { url: `${BASE}/` }); await sleep(2600)
  await click('Пропустить'); await sleep(400)

  await send('Page.navigate', { url: `${BASE}/map` }); await sleep(3000)
  await shot('s14-map')

  await send('Page.navigate', { url: `${BASE}/map?view=schema` }); await sleep(3600)
  await shot('s14-schema')

  await ev(`document.querySelectorAll('.karier-marker')[5]?.dispatchEvent(new MouseEvent('click',{bubbles:true}))`)
  await sleep(400)
  await send('Page.navigate', { url: `${BASE}/map` }); await sleep(2600)
  await ev(`document.querySelectorAll('.karier-marker')[5]?.dispatchEvent(new MouseEvent('click',{bubbles:true}))`)
  await sleep(1500)
  await click('развернуть'); await sleep(700)
  await shot('s14-sheet-full')

  await send('Page.navigate', { url: `${BASE}/types` }); await sleep(2600)
  await click('+ Тип'); await sleep(900)
  await shot('s14-modal')

  await send('Page.navigate', { url: `${BASE}/registry` }); await sleep(2600)
  await ev(`window.scrollTo(0, document.body.scrollHeight)`); await sleep(600)
  await shot('s14-registry-bottom')

  await send('Page.navigate', { url: `${BASE}/inspections` }); await sleep(2600)
  await ev(`window.scrollTo(0, document.body.scrollHeight)`); await sleep(600)
  await shot('s14-inspections-bottom')

  console.log('errors:', errors.length ? errors.slice(0, 3) : 'none')
}

try { await main() } catch (e) { console.error('FAILED:', e.message); process.exitCode = 1 }
finally { try { ws?.close() } catch {}; browser.kill() }
