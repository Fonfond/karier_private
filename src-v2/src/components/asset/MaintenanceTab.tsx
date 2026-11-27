import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../../lib/api'
import { gisApi } from '../../lib/gis'
import { Alert } from '../ui'

type Entry = {
  id: string
  at: string
  kind: string
  motor_hours: number | null
  fuel_liters: number | null
  fuel_level_pct: number | null
  cost: number | null
  note: string | null
  author_name: string | null
}

const KIND_LABEL: Record<string, string> = {
  to: 'ТО',
  fuel: 'Заправка',
  repair: 'Ремонт',
  other: 'Прочее',
}

/** Журнал ТО: моточасы, топливо, ремонты. */
export function MaintenanceTab({ assetId }: { assetId: string }) {
  const [entries, setEntries] = useState<Entry[]>([])
  const [kind, setKind] = useState('to')
  const [motorHours, setMotorHours] = useState('')
  const [fuelLevel, setFuelLevel] = useState('')
  const [fuelLiters, setFuelLiters] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await gisApi.maintenanceList(assetId)
      setEntries(data)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить журнал ТО')
    }
  }, [assetId])

  useEffect(() => {
    void load()
  }, [load])

  const add = async () => {
    setBusy(true)
    try {
      await gisApi.maintenanceAdd(assetId, {
        kind,
        motor_hours: motorHours ? Number(motorHours) : null,
        fuel_level_pct: fuelLevel ? Number(fuelLevel) : null,
        fuel_liters: fuelLiters ? Number(fuelLiters) : null,
        note: note.trim() || null,
      })
      setMotorHours('')
      setFuelLevel('')
      setFuelLiters('')
      setNote('')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось добавить запись')
    } finally {
      setBusy(false)
    }
  }

  const latest = entries[0]

  return (
    <div className="space-y-3 text-[13px]">
      {error ? <Alert kind="error">{error}</Alert> : null}

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg bg-surface2/60 px-2.5 py-2">
          <div className="text-[11px] text-ink3">Моточасы</div>
          <div className="text-[15px] text-ink">{latest?.motor_hours ?? '—'}</div>
        </div>
        <div className="rounded-lg bg-surface2/60 px-2.5 py-2">
          <div className="text-[11px] text-ink3">Топливо</div>
          <div className="text-[15px] text-ink">
            {latest?.fuel_level_pct != null ? `${latest.fuel_level_pct}%` : '—'}
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-line p-2.5">
        <div className="mb-2 text-[12px] uppercase tracking-wide text-ink3">Новая запись</div>
        <div className="grid grid-cols-2 gap-2">
          <label className="text-[11px] text-ink3">
            Тип
            <select className="input mt-1 h-8" value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.entries(KIND_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label className="text-[11px] text-ink3">
            Моточасы
            <input className="input mt-1 h-8" inputMode="decimal" value={motorHours} onChange={(e) => setMotorHours(e.target.value)} />
          </label>
          <label className="text-[11px] text-ink3">
            Топливо, %
            <input className="input mt-1 h-8" inputMode="decimal" value={fuelLevel} onChange={(e) => setFuelLevel(e.target.value)} />
          </label>
          <label className="text-[11px] text-ink3">
            Заправлено, л
            <input className="input mt-1 h-8" inputMode="decimal" value={fuelLiters} onChange={(e) => setFuelLiters(e.target.value)} />
          </label>
        </div>
        <label className="mt-2 block text-[11px] text-ink3">
          Примечание
          <input className="input mt-1 h-8" value={note} onChange={(e) => setNote(e.target.value)} placeholder="ТО-1, замена масла" />
        </label>
        <button type="button" className="btn-primary mt-2 h-9 w-full" disabled={busy} onClick={() => void add()}>
          Добавить запись
        </button>
      </div>

      <div className="space-y-1.5">
        <div className="text-[12px] uppercase tracking-wide text-ink3">История</div>
        {entries.length === 0 ? (
          <p className="text-[12px] text-ink3">Записей пока нет</p>
        ) : (
          entries.map((entry) => (
            <div key={entry.id} className="rounded-lg bg-surface2/50 px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{KIND_LABEL[entry.kind] ?? entry.kind}</span>
                <span className="text-[11px] text-ink3">{new Date(entry.at).toLocaleDateString('ru-RU')}</span>
              </div>
              <div className="mt-0.5 text-[12px] text-ink2">
                {entry.motor_hours != null ? `моточасы ${entry.motor_hours} · ` : ''}
                {entry.fuel_level_pct != null ? `топливо ${entry.fuel_level_pct}% · ` : ''}
                {entry.fuel_liters != null ? `заправка ${entry.fuel_liters} л` : ''}
              </div>
              {entry.note ? <div className="text-[11px] text-ink3">{entry.note}</div> : null}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
