import { useRef } from 'react'
import { QRCodeSVG } from 'qrcode.react'

interface Props {
  open: boolean
  asset: { id: string; code: string; name: string }
  onClose: () => void
}

export function QrModal({ open, asset, onClose }: Props) {
  const holder = useRef<HTMLDivElement>(null)
  if (!open) return null

  const url = `${window.location.origin}/asset/${asset.id}`

  const print = () => {
    const svg = holder.current?.querySelector('svg')?.outerHTML ?? ''
    const win = window.open('', '_blank', 'width=420,height=560')
    if (!win) return
    win.document.write(`<!doctype html><html lang="ru"><head><meta charset="utf-8">
      <title>QR ${asset.code}</title>
      <style>
        body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px; text-align: center; }
        .card { border: 2px solid #111; border-radius: 16px; padding: 20px; }
        .code { font: 700 26px/1.2 ui-monospace, monospace; margin-top: 12px; }
        .name { font-size: 15px; margin-top: 6px; }
        .hint { font-size: 11px; color: #555; margin-top: 10px; }
        svg { width: 260px; height: 260px; }
      </style></head><body>
      <div class="card">
        ${svg}
        <div class="code">${asset.code}</div>
        <div class="name">${asset.name}</div>
        <div class="hint">Отсканируйте камерой телефона — откроется карточка объекта</div>
      </div>
      <script>setTimeout(() => { window.print() }, 300)</script>
      </body></html>`)
    win.document.close()
  }

  return (
    <div className="fixed inset-0 z-[1600] flex items-center justify-center bg-black/75 p-4 backdrop-blur">
      <div className="w-full max-w-[380px] rounded-2xl border border-line bg-surface1 p-5">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <div className="text-[15px] font-semibold">QR-код объекта</div>
            <div className="text-[12px] text-ink3">Наклейка на шкаф или опору</div>
          </div>
          <button type="button" className="btn-ghost h-9 px-3 text-[12px]" onClick={onClose}>
            Закрыть
          </button>
        </div>

        <div ref={holder} className="mx-auto w-fit rounded-xl bg-white p-3">
          <QRCodeSVG value={url} size={220} level="M" bgColor="#ffffff" fgColor="#0B1014" />
        </div>

        <div className="mt-3 text-center">
          <div className="font-mono text-[16px] font-semibold">{asset.code}</div>
          <div className="text-[12px] text-ink2">{asset.name}</div>
          <div className="mt-1 break-all text-[10px] text-ink3">{url}</div>
        </div>

        <div className="mt-4 flex gap-2">
          <button type="button" className="btn-primary flex-1" onClick={print}>
            🖨 Печать QR
          </button>
          <button type="button" className="btn-ghost" onClick={onClose}>
            Готово
          </button>
        </div>
      </div>
    </div>
  )
}
