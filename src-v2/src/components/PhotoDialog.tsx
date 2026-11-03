import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { Alert } from './ui'
import { processPhoto } from '../lib/photo'
import type { PhotoResult } from '../lib/photo'

interface Props {
  open: boolean
  assetCode: string
  title?: string
  hint?: string
  onClose: () => void
  onCaptured: (photo: PhotoResult) => void
}

/**
 * Съёмка фото: EXIF → гео → водяной знак на canvas → предпросмотр.
 * Работает и без сети: всё считается на устройстве.
 */
export function PhotoDialog({ open, assetCode, title, hint, onClose, onCaptured }: Props) {
  const { user } = useAuth()
  const inputRef = useRef<HTMLInputElement>(null)
  const [photo, setPhoto] = useState<PhotoResult | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) {
      setPhoto(null)
      setError(null)
      if (preview) URL.revokeObjectURL(preview)
      setPreview(null)
    }
  }, [open, preview])

  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview)
    }
  }, [preview])

  if (!open) return null

  const handleFile = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      const result = await processPhoto(file, {
        assetCode,
        authorName: user?.full_name ?? 'неизвестный',
        authorTabNo: user?.tab_no ?? '—',
      })
      if (preview) URL.revokeObjectURL(preview)
      setPhoto(result)
      setPreview(URL.createObjectURL(result.blob))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось обработать фото')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[1600] flex items-end justify-center bg-black/70 p-0 backdrop-blur sm:items-center sm:p-4">
      <div className="w-full max-w-[540px] rounded-t-2xl border border-line bg-surface1 p-4 shadow-sheet sm:rounded-2xl">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <div className="text-[15px] font-semibold">{title ?? 'Фото объекта'}</div>
            <div className="text-[12px] text-ink3">{hint ?? 'Дата, координаты и автор впечатаются в фото'}</div>
          </div>
          <button type="button" className="btn-ghost h-9 px-3 text-[12px]" onClick={onClose}>
            Закрыть
          </button>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void handleFile(file)
          }}
        />

        {!photo ? (
          <button
            type="button"
            className="btn-primary h-14 w-full text-[15px]"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
          >
            {busy ? 'Обрабатываем…' : '📷 Сделать фото'}
          </button>
        ) : (
          <div className="space-y-3">
            {preview ? (
              <img src={preview} alt="Фото с водяным знаком" className="max-h-[46vh] w-full rounded-xl object-contain" />
            ) : null}
            <div className="rounded-lg bg-surface2/70 px-3 py-2 text-[11px] leading-relaxed text-ink2">
              <div>{photo.watermark}</div>
              <div className="mt-1 text-ink3">
                {photo.geo.source === 'exif'
                  ? 'Координаты из EXIF камеры'
                  : photo.geo.source === 'device'
                    ? 'Координаты устройства'
                    : 'Координаты недоступны'}
                {' · '}
                {photo.width}×{photo.height}
              </div>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn-primary flex-1"
                onClick={() => {
                  onCaptured(photo)
                  setPhoto(null)
                  if (preview) URL.revokeObjectURL(preview)
                  setPreview(null)
                }}
              >
                Использовать фото
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => {
                  setPhoto(null)
                  if (preview) URL.revokeObjectURL(preview)
                  setPreview(null)
                  inputRef.current?.click()
                }}
              >
                Переснять
              </button>
            </div>
          </div>
        )}

        {error ? (
          <div className="mt-3">
            <Alert kind="error">{error}</Alert>
          </div>
        ) : null}
      </div>
    </div>
  )
}
