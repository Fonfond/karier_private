import { powerStateOf, voltageText } from '../../lib/power'

interface Props {
  status: string | null | undefined
  grounded?: boolean | null
  /** Номинал напряжения: показываем «6 кВ» только когда объект под напряжением. */
  voltageKv?: number | null
  size?: 'sm' | 'md'
  className?: string
}

/**
 * Индикатор электробезопасности: красный — под напряжением, зелёный — обесточено.
 *
 * Цвет всегда продублирован текстом и иконкой (доступность): состояние читается
 * скринридером (`role="status"` + `aria-label`) и понятно без цвета.
 */
export function PowerStateBadge({ status, grounded, voltageKv, size = 'md', className = '' }: Props) {
  const power = powerStateOf(status, grounded)
  const text = size === 'sm' ? 'text-[11px]' : 'text-[12px]'
  const padding = size === 'sm' ? 'px-1.5 py-0.5' : 'px-2 py-1'
  const voltage =
    power.energized && voltageKv != null && Number.isFinite(voltageKv)
      ? voltageText(true, voltageKv)
      : null
  return (
    <span
      role="status"
      aria-label={`Электробезопасность: ${power.title}`}
      title={power.title}
      data-power={power.kind}
      className={`inline-flex items-center gap-1 rounded-full border ${text} ${padding} ${className}`}
      style={{
        color: power.color,
        borderColor: `${power.color}66`,
        background: `${power.color}1A`,
      }}
    >
      <span aria-hidden="true" style={{ color: power.color }}>
        {power.icon}
      </span>
      <span>{power.label}</span>
      {voltage ? <span className="font-mono">{voltage}</span> : null}
    </span>
  )
}

/** Точка-индикатор для плотных строк списков: цвет + подпись рядом (текст обязателен). */
export function PowerDot({ status, grounded }: { status: string | null | undefined; grounded?: boolean | null }) {
  const power = powerStateOf(status, grounded)
  return (
    <span
      aria-hidden="true"
      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
      style={{ background: power.color }}
      data-power={power.kind}
      title={power.title}
    />
  )
}
