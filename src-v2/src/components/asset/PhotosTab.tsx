import { useCallback, useEffect, useState } from 'react'
import { Alert } from '../ui'
import { ApiError } from '../../lib/api'
import type { MediaItem } from '../../lib/opsApi'
import { opsApi } from '../../lib/opsApi'
import { useAuth } from '../../auth/AuthProvider'
import { PhotoDialog } from '../PhotoDialog'
import { formatCoords } from '../../lib/photo'
import type { PhotoResult } from '../../lib/photo'

export function PhotosTab({ assetId, assetCode }: { assetId: string; assetCode: string }) {
  const { user, can } = useAuth()
  const [items, setItems] = useState<MediaItem[]>([])
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [viewer, setViewer] = useState<MediaItem | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await opsApi.photos(assetId)
      setItems(data.items)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить фото')
    }
  }, [assetId])

  useEffect(() => {
    void load()
  }, [load])

  const upload = async (photo: PhotoResult) => {
    try {
      await opsApi.uploadPhoto(assetId, photo, 'inspection')
      setNotice('Фото загружено с метаданными')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить фото')
    }
  }

  const remove = async (item: MediaItem) => {
    try {
      await opsApi.deletePhoto(item.id)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось удалить фото')
    }
  }

  return (
    <div className="space-y-3">
      <button type="button" className="btn-primary h-11 w-full" onClick={() => setDialogOpen(true)}>
        📷 Добавить фото
      </button>

      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      {items.length === 0 ? (
        <p className="hint">Фотографий пока нет. При съёмке в изображение впечатываются дата, координаты и автор.</p>
      ) : (
        <div className="grid grid-cols-3 gap-2">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              className="group relative aspect-square overflow-hidden rounded-lg bg-surface2"
              onClick={() => setViewer(item)}
            >
              <img src={item.content_url} alt="Фото объекта" className="h-full w-full object-cover" loading="lazy" />
              <span className="absolute inset-x-0 bottom-0 bg-black/60 px-1 py-0.5 text-[9px] text-white">
                {item.captured_at ? new Date(item.captured_at).toLocaleDateString('ru-RU') : ''}
              </span>
            </button>
          ))}
        </div>
      )}

      <PhotoDialog
        open={dialogOpen}
        assetCode={assetCode}
        title="Фото объекта"
        onClose={() => setDialogOpen(false)}
        onCaptured={(photo) => {
          setDialogOpen(false)
          void upload(photo)
        }}
      />

      {viewer ? (
        <div className="fixed inset-0 z-[1550] flex flex-col bg-black/85 p-3">
          <div className="mb-2 flex items-center justify-between gap-3 rounded-xl bg-surface1 px-3 py-2">
            <div className="min-w-0 text-[12px]">
              <div className="truncate">{viewer.author_name} · таб. {viewer.author_tab_no}</div>
              <div className="text-[11px] text-ink3">
                {viewer.captured_at
                  ? new Date(viewer.captured_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
                  : ''}
                {viewer.lat !== null && viewer.lon !== null
                  ? ` · ${formatCoords({
                      lat: viewer.lat,
                      lon: viewer.lon,
                      accuracy: viewer.accuracy_m,
                      source: viewer.geo_source as 'exif' | 'device' | 'asset' | 'manual' | 'none',
                    })}`
                  : ''}
              </div>
            </div>
            <div className="flex gap-2">
              {(can('document.manage') || viewer.author_tab_no === user?.tab_no) ? (
                <button type="button" className="btn-ghost h-9 px-3 text-[12px] text-bad" onClick={() => void remove(viewer)}>
                  Удалить
                </button>
              ) : null}
              <button type="button" className="btn-ghost h-9 px-3 text-[12px]" onClick={() => setViewer(null)}>
                Закрыть
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-hidden rounded-xl">
            <img src={viewer.content_url} alt="Фото" className="h-full w-full object-contain" />
          </div>
          <div className="mt-2 rounded-lg bg-surface1/90 px-3 py-2 text-[11px] text-ink2">
            {viewer.watermark_applied ?? 'Водяной знак не сохранён'}
            <div className="mt-1 text-[10px] text-ink3">sha256: {viewer.sha256?.slice(0, 32)}…</div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
