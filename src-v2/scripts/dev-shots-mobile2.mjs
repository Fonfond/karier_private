/** Мобильные скриншоты: навигация, карта, шторка, реестр, схема (iPhone 13 / Pixel 5). */

import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9343
const BASE = 'http://127.0.0.1:5174'
const OUT = 'C:\\karier\\.tmp'
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile-mobile2'

const browser = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${PROFILE}`, '--no-first-run', '--disable-gpu', '--no-sandbox',
  '--hide-scrollbars', '--window-size=390,844', 'about:blank'], { stdio: 'ignore' })

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
const waitFor = async (expr, ms = 15000) => {
  const start = Date.now()
  while (Date.now() - start < ms) { if (await ev(expr)) return true; await sleep(250) }
  return false
}
const click = (text) => ev(`(() => {
  const n = [...document.querySelectorAll('button, a, label')].find(x => x.textContent.trim().includes(${JSON.stringify(text)}));
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
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 3, mobile: true, screenWidth: 390, screenHeight: 844 })
  await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 })

  await send('Page.navigate', { url: `${BASE}/login` }); await sleep(2200)
  await ev(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tab_no:'000001',password:'admin'}),credentials:'include'}).then(r=>r.status)`)

  await send('Page.navigate', { url: `${BASE}/` }); await sleep(3000)
  await waitFor(`document.body.innerText.includes('Под напряжением')`)
  await click('Пропустить'); await sleep(500)
  console.log('нижняя навигация:', await ev(`!!document.querySelector('nav.fixed')`))
  console.log('верхнее меню скрыто:', await ev(`(() => { const nav=[...document.querySelectorAll('header nav')][0]; return nav ? getComputedStyle(nav).display === 'none' : true })()`))
  await shot('s13-dashboard')

  await send('Page.navigate', { url: `${BASE}/map` }); await sleep(3200)
  await waitFor(`document.querySelectorAll('.karier-marker').length > 0`)
  console.log('кнопки зума 48px:', await ev(`(() => { const b=[...document.querySelectorAll('button')].find(x=>x.getAttribute('aria-label')==='Приблизить'); if(!b) return 0; const r=b.getBoundingClientRect(); return Math.round(r.width)+'x'+Math.round(r.height) })()`))
  console.log('FAB:', await ev(`!!document.querySelector('[aria-label="Добавить объект"]')`))
  await shot('s13-map')

  await ev(`document.querySelectorAll('.karier-marker')[5]?.dispatchEvent(new MouseEvent('click',{bubbles:true}))`)
  await sleep(1800)
  const sheetHeight = () => ev(`(() => { const s=document.querySelector('section[role="dialog"]'); return s ? Math.round(s.getBoundingClientRect().height) : 0 })()`)
  console.log('шторка half:', await sheetHeight())
  await shot('s13-sheet-half')
  await click('свернуть'); await sleep(700)
  console.log('шторка peek:', await sheetHeight())
  await shot('s13-sheet-peek')
  await click('развернуть'); await sleep(700)
  console.log('шторка full:', await sheetHeight())

  await send('Page.navigate', { url: `${BASE}/registry` }); await sleep(2600)
  console.log('таблица скрыта на мобиле:', await ev(`(() => { const t=document.querySelector('table'); return t ? getComputedStyle(t.closest('div')).display === 'none' : true })()`))
  console.log('карточек в списке:', await ev(`document.querySelectorAll('.card').length`))
  await shot('s13-registry')

  await send('Page.navigate', { url: `${BASE}/map?view=schema` }); await sleep(3200)
  console.log('схема открыта:', await ev(`!!document.querySelector('.react-flow')`))
  console.log('порт (CSS):', await ev(`(() => { const h=[...document.querySelectorAll('.react-flow__handle')].find(x=>x.getBoundingClientRect().width>0); return h ? getComputedStyle(h).width : 0 })()`))
  await shot('s13-schema')

  console.log('overflow-x:', await ev(`document.documentElement.scrollWidth - document.documentElement.clientWidth`))
  console.log('errors:', errors.length ? errors.slice(0, 3) : 'none')
}

try { await main() } catch (e) { console.error('FAILED:', e.message); process.exitCode = 1 }
finally { try { ws?.close() } catch {}; browser.kill() }
