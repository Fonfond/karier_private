import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { PhotoDialog } from '../components/PhotoDialog'
import { Alert, Badge, PageTitle } from '../components/ui'
import { ApiError } from '../lib/api'
import type { Defect } from '../lib/opsApi'
import { DEFECT_STATUS_LABEL, SEVERITY_COLOR, SEVERITY_LABEL, opsApi } from '../lib/opsApi'
import { openExport } from '../lib/dashboard'
import type { PhotoResult } from '../lib/photo'

const STATUS_TONE: Record<string, 'ok' | 'bad' | 'warm' | 'accent' | 'neutral'> = {
  open: 'bad',
  in_progress: 'warm',
  fixed: 'accent',
  accepted: 'ok',
  rejected: 'neutral',
}

export function DefectsPage() {
  const { can } = useAuth()
  const [items, setItems] = useState<Defect[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [fixing, setFixing] = useState<Defect | null>(null)
  const [photoOpen, setPhotoOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  const canManage = can('defect.manage') && can('asset.create')

  const load = useCallback(async () => {
    try {
      const data = await opsApi.defects({
        status: statusFilter || undefined,
        severity: severityFilter || undefined,
      })
      setItems(data.items)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить дефекты')
    }
  }, [statusFilter, severityFilter])

  useEffect(() => {
    void load()
  }, [load])

  const stats = useMemo(
    () => ({
      open: items.filter((item) => item.status === 'open').length,
      critical: items.filter((item) => item.severity === 'critical').length,
    }),
    [items],
  )

  const applyFix = async (defect: Defect, photo: PhotoResult) => {
    setBusy(true)
    setError(null)
    try {
      const media = await opsApi.uploadPhoto(defect.asset.id, photo, 'defect', { defectId: defect.id })
      await opsApi.updateDefect(defect.id, { status: 'fixed', photo_after_id: media.id })
      setNotice(`Дефект на ${defect.asset.code} переведён в «устранён»`)
      setFixing(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось закрыть дефект')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <PageTitle
        title="Дефекты"
        subtitle="Открытые замечания по объектам. Закрытие требует фото «после»"
      />

      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      <div className="card flex flex-wrap items-center gap-2">
        <select className="input h-10 w-auto" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">Все статусы</option>
          {Object.entries(DEFECT_STATUS_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select className="input h-10 w-auto" value={severityFilter} onChange={(e) => setSeverityFilter(e.target.value)}>
          <option value="">Любая критичность</option>
          {Object.entries(SEVERITY_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <span className="ml-auto text-[12px] text-ink3">
          всего {items.length} · открытых {stats.open} · критичных {stats.critical}
        </span>
        {can('report.export') ? (
          <button
            type="button"
            className="btn-ghost h-10 px-3 text-[12px]"
            onClick={() => void openExport('defects')}
          >
            ⬇ Excel
          </button>
        ) : null}
      </div>

      <div className="space-y-2">
        {items.map((defect) => (
          <div key={defect.id} className="card flex flex-wrap gap-4 p-4">
            {defect.photo_before ? (
              <a
                href={defect.photo_before.content_url}
                target="_blank"
                rel="noreferrer"
                className="block h-20 w-24 shrink-0 overflow-hidden rounded-lg bg-surface2"
              >
                <img src={defect.photo_before.content_url} alt="Фото дефекта" className="h-full w-full object-cover" />
              </a>
            ) : (
              <div className="grid h-20 w-24 shrink-0 place-items-center rounded-lg bg-surface2 text-ink3">нет фото</div>
            )}

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[14px] font-medium">{defect.asset.code}</span>
                <span className="truncate text-[13px] text-ink2">{defect.asset.name}</span>
                <span
                  className="rounded-full px-2 py-0.5 text-[11px]"
                  style={{
                    background: `${SEVERITY_COLOR[defect.severity]}22`,
                    color: SEVERITY_COLOR[defect.severity],
                  }}
                >
                  {SEVERITY_LABEL[defect.severity]}
                </span>
                <Badge tone={STATUS_TONE[defect.status] ?? 'neutral'}>
                  {DEFECT_STATUS_LABEL[defect.status] ?? defect.status}
                </Badge>
              </div>
              <div className="mt-1 text-[13px]">{defect.description}</div>
              <div className="mt-1 text-[11px] text-ink3">
                {new Date(defect.detected_at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })}
                {defect.detected_by_name ? ` · ${defect.detected_by_name}` : ''}
                {defect.fixed_at
                  ? ` · устранён ${new Date(defect.fixed_at).toLocaleDateString('ru-RU')}`
                  : ''}
              </div>
            </div>

            <div className="flex shrink-0 flex-wrap items-start gap-2">
              {defect.photo_after ? (
                <a
                  href={defect.photo_after.content_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block h-16 w-20 overflow-hidden rounded-lg border border-ok/40"
                >
                  <img src={defect.photo_after.content_url} alt="Фото после" className="h-full w-full object-cover" />
                </a>
              ) : null}
              {canManage && (defect.status === 'open' || defect.status === 'in_progress') ? (
                <button
                  type="button"
                  className="btn-primary h-9 px-3 text-[12px]"
                  disabled={busy}
                  onClick={() => {
                    setFixing(defect)
                    setPhotoOpen(true)
                  }}
                >
                  Устранить
                </button>
              ) : null}
              {canManage && defect.status === 'fixed' ? (
                <button
                  type="button"
                  className="btn-ghost h-9 px-3 text-[12px]"
                  onClick={async () => {
                    await opsApi.updateDefect(defect.id, { status: 'accepted' })
                    await load()
                  }}
                >
                  Принять
                </button>
              ) : null}
            </div>
          </div>
        ))}

        {items.length === 0 ? (
          <div className="card text-center text-[13px] text-ink3">Дефектов нет — это хорошая новость</div>
        ) : null}
      </div>

      <PhotoDialog
        open={photoOpen && Boolean(fixing)}
        assetCode={fixing?.asset.code ?? ''}
        title="Фото «после»"
        hint="Подтверждение устранения: дата, координаты и автор впечатаются в фото"
        onClose={() => {
          setPhotoOpen(false)
          setFixing(null)
        }}
        onCaptured={(photo) => {
          if (fixing) void applyFix(fixing, photo)
          setPhotoOpen(false)
        }}
      />
    </div>
  )
}
