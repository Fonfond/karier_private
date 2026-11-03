import { useState } from 'react'
import { Alert } from '../ui'
import { ApiError } from '../../lib/api'
import type { AssetOut } from '../../lib/gis'
import { gisApi } from '../../lib/gis'

interface Props {
  asset: AssetOut
  onChanged: (asset: AssetOut) => void
  compact?: boolean
}

/**
 * Оперативные переключения: включить/отключить и заземление.
 * Заземление требует причины и подтверждения — как в журнале переключений.
 */
export function StateControls({ asset, onChanged, compact = false }: Props) {
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [askGround, setAskGround] = useState(false)
  const [reason, setReason] = useState('')

  const apply = async (payload: { status?: string; grounded?: boolean; reason?: string }) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const result = await gisApi.setState(asset.id, payload)
      onChanged(result.asset)
      if (result.affected_assets > 0) {
        setNotice(
          `Состояние изменено. Затронуто объектов: ${result.affected_assets}` +
            (result.energization_changed ? ' (изменилось наличие питания)' : ''),
        )
      } else {
        setNotice('Состояние изменено')
      }
      setAskGround(false)
      setReason('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось изменить состояние')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={compact ? 'space-y-2' : 'space-y-3'}>
      <div className="flex flex-wrap gap-2">
        {asset.status === 'on' ? (
          <button
            type="button"
            className="btn-danger h-10 px-3 text-[13px]"
            disabled={busy}
            onClick={() => void apply({ status: 'off', reason: 'оперативное отключение' })}
          >
            Отключить
          </button>
        ) : (
          <button
            type="button"
            className="btn-primary h-10 px-3 text-[13px]"
            disabled={busy}
            onClick={() => void apply({ status: 'on', reason: 'оперативное включение' })}
          >
            Включить
          </button>
        )}
        <button
          type="button"
          className={
            asset.grounded ? 'btn-ghost h-10 border-ground/50 px-3 text-[13px] text-ground' : 'btn-ghost h-10 px-3 text-[13px]'
          }
          disabled={busy}
          onClick={() => (asset.grounded ? void apply({ grounded: false, reason: 'заземление снято' }) : setAskGround(true))}
        >
          {asset.grounded ? '⏚ Снять заземление' : '⏚ Заземлить'}
        </button>
      </div>

      {askGround && !asset.grounded ? (
        <div className="rounded-xl border border-warm/40 bg-warm/10 p-3">
          <p className="mb-2 text-[12px] text-warm">
            Убедитесь, что объект отключён и напряжение отсутствует. Заземление будет записано в журнал
            переключений.
          </p>
          <input
            className="input h-10 text-[13px]"
            placeholder="Причина: работы на линии, наряд №…"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              className="btn-danger h-9 px-3 text-[12px]"
              disabled={busy || reason.trim().length < 3}
              onClick={() => void apply({ grounded: true, reason: reason.trim() })}
            >
              Подтвердить заземление
            </button>
            <button
              type="button"
              className="btn-ghost h-9 px-3 text-[12px]"
              onClick={() => setAskGround(false)}
            >
              Отмена
            </button>
          </div>
        </div>
      ) : null}

      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}
    </div>
  )
}
