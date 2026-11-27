import { useState } from 'react'
import { ApiError } from '../../lib/api'
import type { ToggleResult } from '../../lib/gis'
import { POWER_COLOR, gisApi } from '../../lib/gis'
import { powerStateOf, toggleAriaLabel } from '../../lib/power'

interface Props {
  assetId: string
  name: string
  status: string
  grounded?: boolean | null
  /** Компактный вариант для строк таблицы/списка. */
  compact?: boolean
  disabled?: boolean
  onToggled?: (result: ToggleResult) => void
}

/**
 * Кнопка «Включить/Отключить» для ячейки, разъединителя или коммутационного
 * аппарата: `POST /api/assets/{id}/toggle`, состояние и напряжение возвращает API.
 *
 * Цвет кнопки — цвет результата действия: «Включить» ведёт к красному
 * (под напряжением), «Отключить» — к зелёному (обесточено). Рядом всегда текст
 * и `aria-label` с текущим состоянием.
 */
export function PowerToggleButton({
  assetId,
  name,
  status,
  grounded,
  compact = false,
  disabled = false,
  onToggled,
}: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const power = powerStateOf(status, grounded)
  const next: 'on' | 'off' = power.energized ? 'off' : 'on'
  const targetColor = power.energized ? POWER_COLOR.off : POWER_COLOR.on

  const run = async () => {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const result = await gisApi.toggleAsset(assetId, { state: next })
      onToggled?.(result)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.status === 403
            ? 'Нет права переключать'
            : err.status === 422
              ? 'Объект нельзя переключать'
              : err.message,
        )
      } else {
        setError('Не удалось переключить')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="inline-flex flex-col items-start gap-0.5">
      <button
        type="button"
        data-testid={`power-toggle-${assetId}`}
        className={`shrink-0 rounded-lg border font-semibold transition disabled:opacity-50 ${
          compact ? 'h-7 px-2 text-[11px]' : 'h-9 px-3 text-[12px]'
        }`}
        style={{ color: targetColor, borderColor: targetColor, background: `${targetColor}14` }}
        disabled={busy || disabled}
        aria-label={toggleAriaLabel(next, name, power)}
        title={power.energized ? `Отключить «${name}» — обесточить` : `Включить «${name}» — подать напряжение`}
        onClick={(event) => {
          event.stopPropagation()
          void run()
        }}
      >
        {busy ? '…' : power.energized ? 'Отключить' : 'Включить'}
      </button>
      {error ? (
        <span role="alert" className="text-[10px] text-bad">
          {error}
        </span>
      ) : null}
    </span>
  )
}
