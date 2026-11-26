/** Аудит: пересекаются ли интерактивные элементы с нижней навигацией. */

import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9344
const BASE = 'http://127.0.0.1:5174'
const PROFILE = 'C:\\karier\\.tmp\\chrome-profile-audit'
const OUT = 'C:\\karier\\.tmp'

const ROUTES = ['/', '/map', '/map?view=schema', '/registry', '/defects', '/inspections', '/types', '/employees', '/audit', '/sync', '/profile']

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
}

const AUDIT = `(() => {
  const nav = document.querySelector('nav.fixed');
  if (!nav) return { nav: false, overlaps: [], total: 0 };
  const navRect = nav.getBoundingClientRect();
  const nodes = [...document.querySelectorAll('button, a, input, select, textarea, [role="button"]')];
  const overlaps = [];
  for (const node of nodes) {
    if (nav.contains(node)) continue;
    const style = getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) continue;
    const r = node.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const intersects = r.bottom > navRect.top + 2 && r.top < navRect.bottom - 2;
    if (!intersects) continue;
    // элемент должен быть реально виден, а не перекрыт шторкой/модалкой
    const cx = Math.min(Math.max(r.left + r.width / 2, 0), window.innerWidth - 1);
    const cy = Math.min(Math.max(r.top + r.height / 2, 0), window.innerHeight - 1);
    const hit = document.elementFromPoint(cx, cy);
    if (!hit || !(node === hit || node.contains(hit))) continue;
    const label = [node.tagName, node.getAttribute('type') || '', node.getAttribute('placeholder') || '', (node.getAttribute('aria-label') || node.textContent || '').trim().slice(0, 20)].filter(Boolean).join(':');
    overlaps.push(label);
  }
  return { nav: true, navHeight: Math.round(navRect.height), overlaps: overlaps.slice(0, 8), total: overlaps.length };
})()`

async function auditPage(label) {
  const result = await ev(AUDIT)
  console.log(`\n=== ${label} ===`)
  console.log('nav:', result.nav, '| высота:', result.navHeight, '| пересечений:', result.total)
  if (result.total) console.log('  элементы:', result.overlaps.join(' | '))
  return result.total
}

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

  await send('Page.navigate', { url: `${BASE}/login` }); await sleep(2000)
  await ev(`fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tab_no:'000001',password:'admin'}),credentials:'include'}).then(r=>r.status)`)

  let total = 0
  for (const route of ROUTES) {
    await send('Page.navigate', { url: `${BASE}${route}` })
    await sleep(route === '/map?view=schema' ? 4000 : 2600)
    await ev(`(() => { const t=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Пропустить'); t?.click(); return true })()`)
    await sleep(300)
    total += await auditPage(route || '/')
    // прокрутка вниз: последний элемент тоже не должен упираться в панель
    await ev(`window.scrollTo(0, document.body.scrollHeight)`)
    await sleep(500)
    total += await auditPage((route || '/') + ' (низ страницы)')
    await ev(`window.scrollTo(0, 0)`)
  }

  // шторка объекта на карте
  await send('Page.navigate', { url: `${BASE}/map` }); await sleep(3200)
  await ev(`document.querySelectorAll('.karier-marker')[5]?.dispatchEvent(new MouseEvent('click',{bubbles:true}))`)
  await sleep(1600)
  total += await auditPage('/map + шторка (half)')
  await ev(`(() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='развернуть'); b?.click(); return true })()`)
  await sleep(700)
  total += await auditPage('/map + шторка (full)')
  await shot('s14-sheet-full')

  // модалки
  const modalCases = [
    ['/types', '+ Тип', 'модалка типа'],
    ['/registry', '+ Объект', 'модалка объекта'],
    ['/employees', '✎', 'модалка сотрудника'],
  ]
  for (const [route, trigger, label] of modalCases) {
    await send('Page.navigate', { url: `${BASE}${route}` }); await sleep(2600)
    await ev(`(() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim().includes(${JSON.stringify(trigger)})); b?.click(); return true })()`)
    await sleep(900)
    total += await auditPage(label)
  }

  console.log('\nИТОГО пересечений:', total, '| ошибок:', errors.length)
}

try { await main() } catch (e) { console.error('FAILED:', e.message); process.exitCode = 1 }
finally { try { ws?.close() } catch {}; browser.kill() }
