import { useEffect, useRef, useState } from 'react'
import { Html5Qrcode } from 'html5-qrcode'
import { Alert } from './ui'

interface Props {
  open: boolean
  onClose: () => void
  onScanned: (assetId: string) => void
}

const ELEMENT_ID = 'karier-qr-reader'

export function QrScanner({ open, onClose, onScanned }: Props) {
  const scannerRef = useRef<Html5Qrcode | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setStarting(true)

    const start = async () => {
      try {
        const scanner = new Html5Qrcode(ELEMENT_ID, { verbose: false })
        scannerRef.current = scanner
        await scanner.start(
          { facingMode: 'environment' },
          { fps: 10, qrbox: { width: 240, height: 240 } },
          (text) => {
            const match = text.match(/asset\/([0-9a-fA-F-]{36})/)
            const assetId = match ? match[1] : null
            if (!assetId) {
              setError('Это не QR-код объекта')
              return
            }
            void scanner.stop().catch(() => undefined)
            scannerRef.current = null
            onScanned(assetId)
          },
          () => undefined,
        )
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? `Камера недоступна: ${err.message}`
              : 'Камера недоступна. Разрешите доступ в настройках браузера',
          )
        }
      } finally {
        if (!cancelled) setStarting(false)
      }
    }

    void start()

    return () => {
      cancelled = true
      const scanner = scannerRef.current
      scannerRef.current = null
      if (scanner) void scanner.stop().catch(() => undefined)
    }
  }, [open, onScanned])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[1600] flex flex-col bg-black/90 p-4 backdrop-blur">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <div className="text-[15px] font-semibold text-ink">Сканирование QR</div>
          <div className="text-[12px] text-ink3">Наведите камеру на наклейку объекта</div>
        </div>
        <button type="button" className="btn-ghost h-9 px-3 text-[12px]" onClick={onClose}>
          Закрыть
        </button>
      </div>

      <div className="mx-auto w-full max-w-[420px] flex-1 overflow-hidden rounded-2xl bg-black">
        <div id={ELEMENT_ID} className="h-full w-full" />
      </div>

      {starting ? <p className="mt-2 text-center text-[12px] text-ink3">Включаем камеру…</p> : null}
      {error ? (
        <div className="mx-auto mt-3 w-full max-w-[420px]">
          <Alert kind="error">{error}</Alert>
        </div>
      ) : null}
    </div>
  )
}
