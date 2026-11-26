/** Проверка фикса схемы: зум в режиме портов и сохранение позиций в read-only. */

import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9340
const BASE = 'http://127.0.0.1:5174'
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile-s12'

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
const waitFor = async (expr, ms = 15000) => {
  const start = Date.now()
  while (Date.now() - start < ms) { if (await ev(expr)) return true; await sleep(250) }
  return false
}
const clickText = (text) => ev(`(() => {
  const node = [...document.querySelectorAll('button, label')].find(n => n.textContent.trim().includes(${JSON.stringify(text)}));
  if (!node) return false; node.dispatchEvent(new MouseEvent('click', { bubbles: true })); return true;
})()`)
const portStyles = () => ev(`(() => {
  const all = [...document.querySelectorAll('.react-flow__handle')];
  return all.slice(0, 6).map(h => h.style.left + '/' + h.style.top).join(' | ');
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
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })

  await send('Page.navigate', { url: `${BASE}/login` }); await sleep(2000)
  await ev(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tab_no:'000001',password:'admin'}),credentials:'include'}).then(r=>r.status)`)
  await send('Page.navigate', { url: `${BASE}/map` }); await sleep(3200)
  await clickText('Схема'); await sleep(2500)

  const count = () => ev(`document.querySelectorAll('.react-flow__node').length`)
  console.log('nodes на старте:', await count())

  await ev(`(() => { const l=[...document.querySelectorAll('label')].find(n=>n.textContent.includes('Режим редактирования')); l?.querySelector('input')?.click(); return true })()`)
  await sleep(800)
  await ev(`(() => { const l=[...document.querySelectorAll('label')].find(n=>n.textContent.includes('Двигать порты')); l?.querySelector('input')?.click(); return true })()`)
  await sleep(1000)

  // зум и панорамирование в режиме портов
  for (let i = 0; i < 6; i++) {
    await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: 700, y: 500, deltaX: 0, deltaY: i % 2 ? 160 : -160 })
    await sleep(180)
  }
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: 700, y: 500, button: 'middle', clickCount: 1 })
  for (let i = 1; i <= 5; i++) {
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: 700 + i * 12, y: 500 + i * 8, button: 'middle' })
    await sleep(80)
  }
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 760, y: 540, button: 'middle' })
  await sleep(800)

  console.log('nodes после зума/панорамы:', await count())
  console.log('ошибок:', errors.length)

  const before = await portStyles()
  console.log('порты до сохранения:', before)

  // двигаем порт и сохраняем
  const handle = await ev(`(() => {
    const all=[...document.querySelectorAll('.react-flow__handle')];
    const h=all.find(x=>{const r=x.getBoundingClientRect();return r.width>0&&r.top>250&&r.left>300});
    if(!h) return null; const r=h.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2};
  })()`)
  const readHandle = (id) => ev((() => { const h = [...document.querySelectorAll('.react-flow__handle')].find(x => x.getAttribute('data-handleid') === {JSON.stringify(id)}); return h ? h.style.left + '/' + h.style.top : null })())\n  const beforeHandle = handle ? await readHandle(handle.id) : null\n  console.log('перетаскиваем порт', handle?.id, 'из', beforeHandle)\n\n  if (handle) {
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: handle.x, y: handle.y, button: 'left', clickCount: 1 })
    for (let i = 1; i <= 6; i++) {
      await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: handle.x - i * 8, y: handle.y + i * 6, button: 'left' })
      await sleep(60)
    }
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: handle.x - 48, y: handle.y + 36, button: 'left' })
    await sleep(600)
  }
  await clickText('Сохранить раскладку')
  await sleep(2200)

  // уходим на карту и возвращаемся — схема должна открыться в read-only с новыми позициями
  await clickText('Карта'); await sleep(1500)
  await clickText('Схема'); await sleep(2500)
  const afterHandle = handle ? await readHandle(handle.id) : null\n  const after = await portStyles()
  console.log('порты после возврата (read-only):', after)
  console.log('порт после возврата (read-only):', afterHandle)\n  console.log('позиция порта изменилась и сохранилась:', beforeHandle !== null && afterHandle === (await readHandle(handle.id)) && beforeHandle !== afterHandle)

  await sleep(500)
  const shot = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync('C:\\karier\\.tmp\\s12-schema.png', Buffer.from(shot.data, 'base64'))
  console.log('errors:', errors.length ? errors.slice(0, 3) : 'none')
}

try { await main() } catch (e) { console.error('FAILED:', e.message); process.exitCode = 1 }
finally { try { ws?.close() } catch {}; browser.kill() }
