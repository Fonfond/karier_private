import { useState } from 'react'
import { Alert, Badge } from '../ui'
import { ApiError } from '../../lib/api'
import type { ChildAsset } from '../../lib/gis'
import { STATUS_COLOR, STATUS_LABEL, gisApi } from '../../lib/gis'

interface Props {
  parentId: string
  title: string
  children: ChildAsset[]
  canSwitch: boolean
  onClose: () => void
  onChanged: (updated: ChildAsset) => void
}

/** Внутренняя схема РУ: список ячеек с переключением и заземлением. */
export function ChildrenModal({ parentId, title, children, canSwitch, onClose, onChanged }: Props) {
  const [items, setItems] = useState(children)
  const [error, setError] = useState<string | null>(null)
  const [groundingId, setGroundingId] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const refresh = async () => {
    const fresh = await gisApi.children(parentId)
    setItems(fresh)
    fresh.forEach((item) => onChanged(item))
  }

  const apply = async (child: ChildAsset, payload: { status?: string; grounded?: boolean }) => {
    setBusy(child.id)
    setError(null)
    try {
      await gisApi.setState(child.id, {
        ...payload,
        reason: payload.grounded ? reason.trim() : 'оперативное переключение из внутренней схемы',
      })
      await refresh()
      setGroundingId(null)
      setReason('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось изменить состояние')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="fixed inset-0 z-[1500] flex flex-col bg-bg/95 backdrop-blur">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div>
          <div className="text-[15px] font-semibold">{title}</div>
          <div className="text-[11px] text-ink3">Внутренняя структура: ячейки и секции</div>
        </div>
        <button type="button" className="btn-ghost h-9 px-3 text-[12px]" onClick={onClose}>
          Закрыть
        </button>
      </div>

      <div className="mx-auto w-full max-w-3xl flex-1 overflow-y-auto px-4 py-4">
        {error ? <Alert kind="error">{error}</Alert> : null}

        <div className="space-y-2">
          {items.map((child) => {
            const color = STATUS_COLOR[child.status] ?? '#6B7A8A'
            return (
              <div
                key={child.id}
                className={`rounded-xl border bg-surface1 p-3 ${
                  child.grounded ? 'border-ground/60' : 'border-line'
                }`}
              >
                <div className="flex items-center gap-3">
                  <span className="grid h-9 w-9 place-items-center rounded-lg bg-surface2 text-base">
                    {child.type_icon ?? '▭'}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[14px] font-medium">{child.name}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-ink3">
                      <span className="font-mono">{child.code}</span>
                      <span style={{ color }}>
                        ● {STATUS_LABEL[child.status] ?? child.status}
                      </span>
                      {child.energized ? <span className="text-ok">под напряжением</span> : null}
                      {child.grounded ? <span className="text-ground">⏚ заземлено</span> : null}
                    </div>
                  </div>
                  {canSwitch ? (
                    <div className="flex shrink-0 gap-1.5">
                      <button
                        type="button"
                        className={child.status === 'on' ? 'btn-danger h-9 px-2.5 text-[12px]' : 'btn-primary h-9 px-2.5 text-[12px]'}
                        disabled={busy === child.id}
                        onClick={() =>
                          void apply(child, { status: child.status === 'on' ? 'off' : 'on' })
                        }
                      >
                        {child.status === 'on' ? 'Откл' : 'Вкл'}
                      </button>
                      <button
                        type="button"
                        className={`btn-ghost h-9 px-2.5 text-[12px] ${child.grounded ? 'text-ground' : ''}`}
                        disabled={busy === child.id}
                        onClick={() => {
                          if (child.grounded) {
                            void apply(child, { grounded: false })
                          } else {
                            setGroundingId(child.id)
                            setReason('')
                          }
                        }}
                      >
                        ⏚
                      </button>
                    </div>
                  ) : null}
                </div>

                {groundingId === child.id ? (
                  <div className="mt-2 rounded-lg border border-warm/40 bg-warm/10 p-2">
                    <p className="mb-1.5 text-[11px] text-warm">
                      Подтвердите заземление: объект будет обесточен и записан в журнал.
                    </p>
                    <div className="flex gap-2">
                      <input
                        className="input h-9 text-[12px]"
                        placeholder="Причина (наряд, работы)"
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                      />
                      <button
                        type="button"
                        className="btn-danger h-9 px-3 text-[12px]"
                        disabled={reason.trim().length < 3 || busy === child.id}
                        onClick={() => void apply(child, { grounded: true })}
                      >
                        Заземлить
                      </button>
                      <button
                        type="button"
                        className="btn-ghost h-9 px-2 text-[12px]"
                        onClick={() => setGroundingId(null)}
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                ) : null}

                {child.ports.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {child.ports.map((port) => (
                      <span
                        key={port.id}
                        className="rounded border border-line px-1.5 py-0.5 text-[10px] text-ink3"
                      >
                        {port.code}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            )
          })}
          {items.length === 0 ? (
            <div className="rounded-xl border border-line bg-surface1 p-6 text-center text-[13px] text-ink3">
              Внутренних элементов нет
            </div>
          ) : null}
        </div>

        <div className="mt-4 flex items-center gap-2 text-[11px] text-ink3">
          <Badge tone="warm">⏚</Badge> заземление требует причины и попадает в журнал переключений
        </div>
      </div>
    </div>
  )
}
