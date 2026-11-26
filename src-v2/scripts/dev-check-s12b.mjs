/** Точечная проверка: порт двигается, сохраняется и читается в read-only режиме. */

import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9341
const BASE = 'http://127.0.0.1:5174'
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile-s12b'

const browser = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${PROFILE}`, '--no-first-run', '--disable-gpu', '--no-sandbox',
  '--hide-scrollbars', '--window-size=1440,1000', 'about:blank'], { stdio: 'ignore' })

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
const click = (text) => ev(`(() => {
  const n = [...document.querySelectorAll('button, label')].find(x => x.textContent.trim().includes(${JSON.stringify(text)}));
  if (!n) return false; n.dispatchEvent(new MouseEvent('click', { bubbles: true })); return true;
})()`)
const readHandle = (id) => ev(`(() => {
  const h = [...document.querySelectorAll('.react-flow__handle')].find(x => x.getAttribute('data-handleid') === ${JSON.stringify('__ID__')});
  return h ? h.style.left + ' / ' + h.style.top : null;
})()`.replace('__ID__', id))

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
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })

  await send('Page.navigate', { url: `${BASE}/login` }); await sleep(2000)
  await ev(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tab_no:'000001',password:'admin'}),credentials:'include'}).then(r=>r.status)`)
  await send('Page.navigate', { url: `${BASE}/map` }); await sleep(3200)
  await click('Схема'); await sleep(2500)

  await click('Режим редактирования'); await sleep(700)
  await click('Двигать порты'); await sleep(900)

  const handle = await ev(`(() => {
    const all = [...document.querySelectorAll('.react-flow__handle')];
    const h = all.find(x => { const r = x.getBoundingClientRect(); return r.width > 0 && r.top > 300 && r.left > 400; });
    if (!h) return null;
    const r = h.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2, id: h.getAttribute('data-handleid') };
  })()`)
  if (!handle) { console.log('порт не найден'); return }

  const before = await readHandle(handle.id)
  console.log('порт', handle.id.slice(0, 8), 'до:', before)
  console.log('nodes до:', await ev(`document.querySelectorAll('.react-flow__node').length`))

  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: handle.x, y: handle.y, button: 'left', clickCount: 1 })
  for (let i = 1; i <= 8; i++) {
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: handle.x - i * 7, y: handle.y + i * 5, button: 'left' })
    await sleep(50)
  }
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: handle.x - 56, y: handle.y + 40, button: 'left' })
  await sleep(600)

  // зум и панорама — не должны ронять схему
  for (let i = 0; i < 5; i++) {
    await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: 700, y: 500, deltaX: 0, deltaY: i % 2 ? 150 : -150 })
    await sleep(150)
  }
  await sleep(600)
  console.log('nodes после зума:', await ev(`document.querySelectorAll('.react-flow__node').length`), '| ошибок:', errors.length)

  await click('Сохранить раскладку'); await sleep(2200)
  const saved = await readHandle(handle.id)
  console.log('после сохранения:', saved)

  await click('Карта'); await sleep(1500)
  await click('Схема'); await sleep(2600)
  const readonly = await readHandle(handle.id)
  console.log('после возврата (read-only):', readonly)

  await sleep(500)
  const shot = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync('C:\\karier\\.tmp\\s12-schema.png', Buffer.from(shot.data, 'base64'))
  console.log('итог: изменился =', before !== saved, '| read-only совпадает с сохранённым =', readonly === saved)
  console.log('errors:', errors.length ? errors.slice(0, 3) : 'none')
}

try { await main() } catch (e) { console.error('FAILED:', e.message); process.exitCode = 1 }
finally { try { ws?.close() } catch {}; browser.kill() }
