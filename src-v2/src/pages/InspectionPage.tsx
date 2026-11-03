import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { PhotoDialog } from '../components/PhotoDialog'
import { Alert, Badge, PageTitle } from '../components/ui'
import { enqueue } from '../lib/outbox'
import type { Inspection, InspectionItem } from '../lib/opsApi'
import { RESULT_LABEL, SEVERITY_LABEL, opsApi } from '../lib/opsApi'
import type { PhotoResult } from '../lib/photo'
import { resolveId } from '../lib/outbox'
import { useOutbox } from '../lib/useOutbox'
import { ApiError } from '../lib/api'
import { gisApi } from '../lib/gis'

interface LocalInspection {
  id: string
  title: string
  status: string
  items: InspectionItem[]
  startedAt: string
}

const ASSET_CACHE_KEY = 'karier-assets-cache'

export function InspectionPage() {
  const { user } = useAuth()
  const { pending, online, sync } = useOutbox()
  const [inspection, setInspection] = useState<LocalInspection | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [defectAsset, setDefectAsset] = useState<InspectionItem | null>(null)
  const [severity, setSeverity] = useState('medium')
  const [description, setDescription] = useState('')
  const [photo, setPhoto] = useState<PhotoResult | null>(null)
  const [photoOpen, setPhotoOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  const applyServerInspection = (data: Inspection) => {
    setInspection({
      id: data.id,
      title: data.title ?? 'Обход',
      status: data.status,
      items: data.items,
      startedAt: data.started_at,
    })
  }

  const load = useCallback(async () => {
    try {
      const data = await opsApi.inspections(true)
      const active = data.items.find((item) => item.status === 'in_progress')
      if (active) applyServerInspection(active)
      setError(null)
    } catch {
      // офлайн: остаёмся на локальном состоянии
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const startInspection = async () => {
    setError(null)
    try {
      let assets: Array<{ id: string; code: string; name: string; type: { code: string; icon: string | null } }> = []
      try {
        const data = await gisApi.assets()
        assets = data.items
        localStorage.setItem(ASSET_CACHE_KEY, JSON.stringify(data.items))
      } catch {
        const cached = localStorage.getItem(ASSET_CACHE_KEY)
        assets = cached ? JSON.parse(cached) : []
      }

      const scope = assets.filter((asset) => asset.type.code !== 'cell')
      if (scope.length === 0) {
        setError('Нет объектов для обхода — проверьте справочник')
        return
      }

      const tempId = `local-${crypto.randomUUID()}`
      const items: InspectionItem[] = scope.map((asset) => ({
        id: `item-${asset.id}`,
        asset: {
          id: asset.id,
          code: asset.code,
          name: asset.name,
          type_code: asset.type.code,
          type_icon: asset.type.icon,
        },
        result: null,
        comment: null,
        checked_at: null,
        media_count: 0,
      }))

      setInspection({
        id: tempId,
        title: `Обход ${new Date().toLocaleDateString('ru-RU')}`,
        status: 'in_progress',
        items,
        startedAt: new Date().toISOString(),
      })

      await enqueue('inspection_create', {
        tempId,
        kind: 'walk',
        title: `Обход ${new Date().toLocaleDateString('ru-RU')}`,
        asset_ids: scope.map((asset) => asset.id),
      })
      setNotice(
        online
          ? `Обход начат: ${scope.length} объектов`
          : `Обход сохранён на устройстве: ${scope.length} объектов. Отправится при появлении сети`,
      )
      await sync()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось начать обход')
    }
  }

  const markItem = async (item: InspectionItem, result: 'ok' | 'defect') => {
    if (!inspection) return
    setNotice(null)
    setInspection((prev) =>
      prev
        ? {
            ...prev,
            items: prev.items.map((row) =>
              row.id === item.id ? { ...row, result, checked_at: new Date().toISOString() } : row,
            ),
          }
        : prev,
    )
    await enqueue('inspection_item', {
      inspectionId: inspection.id,
      asset_id: item.asset.id,
      result,
      comment: result === 'ok' ? 'без замечаний' : undefined,
    })
    await sync()
    setNotice(result === 'ok' ? `${item.asset.code}: норма` : `${item.asset.code}: отмечен дефект`)
  }

  const submitDefect = async () => {
    if (!inspection || !defectAsset) return
    if (description.trim().length < 3) {
      setError('Опишите дефект (минимум 3 символа)')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const payload: Record<string, unknown> = {
        assetId: defectAsset.asset.id,
        inspectionId: inspection.id,
        severity,
        description: description.trim(),
        category: 'electrical',
      }
      if (photo) {
        payload.photo = {
          capturedAt: photo.capturedAt.toISOString(),
          geo: photo.geo,
          exif: photo.exif,
          width: photo.width,
          height: photo.height,
          watermark: photo.watermark,
        }
      }
      await enqueue('defect', payload, photo?.blob)
      await enqueue('inspection_item', {
        inspectionId: inspection.id,
        asset_id: defectAsset.asset.id,
        result: 'defect',
        comment: description.trim(),
      })

      setInspection((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.map((row) =>
                row.id === defectAsset.id
                  ? { ...row, result: 'defect', comment: description.trim(), checked_at: new Date().toISOString() }
                  : row,
              ),
            }
          : prev,
      )

      setDefectAsset(null)
      setDescription('')
      setPhoto(null)
      setSeverity('medium')
      await sync()
      setNotice(online ? 'Дефект зафиксирован' : 'Дефект сохранён на устройстве и уйдёт при появлении сети')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить дефект')
    } finally {
      setSaving(false)
    }
  }

  const finish = async () => {
    if (!inspection) return
    await enqueue('inspection_submit', { inspectionId: inspection.id })
    setInspection({ ...inspection, status: 'submitted' })
    await sync()
    const realId = await resolveId(inspection.id)
    if (realId !== inspection.id) {
      try {
        applyServerInspection(await opsApi.inspection(realId))
      } catch {
        /* офлайн — оставим локальное состояние */
      }
    }
    setNotice('Обход завершён и отправлен' + (pending > 0 ? ' (часть данных ещё в очереди)' : ''))
  }

  const stats = useMemo(() => {
    const items = inspection?.items ?? []
    return {
      total: items.length,
      checked: items.filter((item) => item.result).length,
      defects: items.filter((item) => item.result === 'defect' || item.result === 'critical').length,
    }
  }, [inspection])

  return (
    <div className="space-y-4">
      <PageTitle
        title="Мой обход"
        subtitle="Отмечайте объекты: норма или дефект. Фото получает дату, координаты и автора автоматически"
      />

      {!online ? (
        <div className="rounded-card border border-warm/40 bg-warm/10 p-3 text-[13px] text-warm">
          Нет сети. Обход сохраняется на устройстве, отправится автоматически. В очереди: {pending}
        </div>
      ) : null}
      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      {loading ? (
        <div className="card text-[13px] text-ink3">Загружаем…</div>
      ) : !inspection ? (
        <div className="card space-y-3">
          <div className="text-[15px] font-semibold">Обход не начат</div>
          <p className="hint">
            Будет создан обход по всем объектам карьера, кроме ячеек распределительных устройств.
            Работает и без интернета.
          </p>
          <button type="button" className="btn-primary px-5" onClick={() => void startInspection()}>
            Начать обход
          </button>
        </div>
      ) : (
        <>
          <div className="card flex flex-wrap items-center gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-[15px] font-semibold">{inspection.title}</div>
              <div className="text-[12px] text-ink3">
                {new Date(inspection.startedAt).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })} ·
                проверено {stats.checked} из {stats.total}
                {stats.defects ? ` · дефектов ${stats.defects}` : ''}
              </div>
            </div>
            <Badge tone={inspection.status === 'submitted' ? 'ok' : 'accent'}>
              {inspection.status === 'submitted' ? 'отправлен' : 'в работе'}
            </Badge>
            {inspection.status !== 'submitted' ? (
              <button type="button" className="btn-ghost h-10 px-3 text-[13px]" onClick={() => void finish()}>
                Завершить обход
              </button>
            ) : null}
          </div>

          <div className="space-y-2">
            {inspection.items.map((item) => {
              const done = Boolean(item.result)
              return (
                <div
                  key={item.id}
                  className={`flex flex-wrap items-center gap-3 rounded-xl border p-3 ${
                    item.result === 'defect' ? 'border-warm/50' : done ? 'border-ok/40' : 'border-line'
                  } bg-surface1`}
                >
                  <span className="text-lg">{item.asset.type_icon ?? '●'}</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[14px] font-medium">{item.asset.name}</div>
                    <div className="text-[11px] text-ink3">
                      <span className="font-mono">{item.asset.code}</span>
                      {item.result ? ` · ${RESULT_LABEL[item.result] ?? item.result}` : ' · не проверен'}
                      {item.comment ? ` · ${item.comment}` : ''}
                    </div>
                  </div>
                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      className={`h-9 rounded-lg px-3 text-[12px] ${item.result === 'ok' ? 'bg-ok/20 text-ok' : 'border border-line text-ink2'}`}
                      onClick={() => void markItem(item, 'ok')}
                    >
                      ✅ Норма
                    </button>
                    <button
                      type="button"
                      className={`h-9 rounded-lg px-3 text-[12px] ${item.result === 'defect' ? 'bg-warm/20 text-warm' : 'border border-line text-ink2'}`}
                      onClick={() => {
                        setDefectAsset(item)
                        setDescription('')
                        setPhoto(null)
                      }}
                    >
                      ⚠️ Дефект
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}

      {defectAsset ? (
        <div className="fixed inset-0 z-[1500] flex items-end justify-center bg-black/70 p-0 backdrop-blur sm:items-center sm:p-4">
          <div className="w-full max-w-[520px] rounded-t-2xl border border-line bg-surface1 p-4">
            <div className="mb-3 flex items-start justify-between gap-3">
              <div>
                <div className="text-[15px] font-semibold">Дефект: {defectAsset.asset.code}</div>
                <div className="text-[12px] text-ink3">{defectAsset.asset.name}</div>
              </div>
              <button type="button" className="btn-ghost h-9 px-3 text-[12px]" onClick={() => setDefectAsset(null)}>
                Закрыть
              </button>
            </div>

            <div className="space-y-3">
              <label className="block">
                <span className="label">Критичность</span>
                <select className="input" value={severity} onChange={(e) => setSeverity(e.target.value)}>
                  {Object.entries(SEVERITY_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block">
                <span className="label">Описание</span>
                <textarea
                  className="input min-h-[90px] py-2"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Что повреждено, где, при каких условиях обнаружено"
                />
              </label>

              {photo ? (
                <div className="rounded-lg bg-surface2/70 px-3 py-2 text-[11px] text-ink2">
                  Фото с водяным знаком готово: {photo.width}×{photo.height}
                </div>
              ) : (
                <button type="button" className="btn-ghost w-full" onClick={() => setPhotoOpen(true)}>
                  📷 Сделать фото дефекта
                </button>
              )}

              <div className="flex gap-2">
                <button
                  type="button"
                  className="btn-primary flex-1"
                  disabled={saving || description.trim().length < 3}
                  onClick={() => void submitDefect()}
                >
                  {saving ? 'Сохраняем…' : 'Зафиксировать дефект'}
                </button>
                <button type="button" className="btn-ghost" onClick={() => setDefectAsset(null)}>
                  Отмена
                </button>
              </div>
              <p className="text-[11px] text-ink3">
                Автор: {user?.full_name} · таб. {user?.tab_no}. Дефект попадёт в раздел «Дефекты» и в историю объекта.
              </p>
            </div>
          </div>
        </div>
      ) : null}

      <PhotoDialog
        open={photoOpen}
        assetCode={defectAsset?.asset.code ?? ''}
        title="Фото дефекта"
        hint="Дата, координаты и автор впечатаются в изображение"
        onClose={() => setPhotoOpen(false)}
        onCaptured={(captured) => {
          setPhoto(captured)
          setPhotoOpen(false)
        }}
      />
    </div>
  )
}
