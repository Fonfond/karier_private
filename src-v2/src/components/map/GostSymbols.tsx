import type { SchemaFrame } from '../../lib/gis'

/** ГОСТ-подобные условные обозначения для однолинейной схемы. */
export function GostSymbol({ symbol, color = '#E6EDF3' }: { symbol: string; color?: string }) {
  const stroke = color
  const common = { stroke, strokeWidth: 1.6, fill: 'none', strokeLinecap: 'round' as const }

  switch (symbol) {
    case 'breaker': // выключатель: контакт с косой чертой
      return (
        <svg viewBox="0 0 48 48" className="h-10 w-10">
          <line x1="24" y1="4" x2="24" y2="16" {...common} />
          <circle cx="24" cy="18" r="2" fill={stroke} />
          <line x1="24" y1="20" x2="34" y2="30" {...common} />
          <circle cx="24" cy="31" r="2" fill={stroke} />
          <line x1="24" y1="33" x2="24" y2="44" {...common} />
          <line x1="30" y1="21" x2="38" y2="21" {...common} strokeWidth={1} />
        </svg>
      )
    case 'disconnector': // разъединитель: два кружка и наклонный нож
      return (
        <svg viewBox="0 0 48 48" className="h-10 w-10">
          <line x1="24" y1="4" x2="24" y2="16" {...common} />
          <circle cx="24" cy="18" r="2.2" fill={stroke} />
          <line x1="25" y1="19" x2="35" y2="29" {...common} />
          <circle cx="24" cy="31" r="2.2" fill={stroke} />
          <line x1="24" y1="33" x2="24" y2="44" {...common} />
        </svg>
      )
    case 'busbar': // секция шин
      return (
        <svg viewBox="0 0 48 48" className="h-10 w-10">
          <line x1="2" y1="20" x2="46" y2="20" {...common} strokeWidth={3.5} />
          <line x1="10" y1="20" x2="10" y2="36" {...common} />
          <line x1="24" y1="20" x2="24" y2="36" {...common} />
          <line x1="38" y1="20" x2="38" y2="36" {...common} />
        </svg>
      )
    case 'generator': // генератор
      return (
        <svg viewBox="0 0 48 48" className="h-10 w-10">
          <circle cx="24" cy="24" r="13" {...common} />
          <text x="24" y="29" textAnchor="middle" fontSize="14" fill={stroke} stroke="none">
            G
          </text>
        </svg>
      )
    case 'source': // питание / ПС
      return (
        <svg viewBox="0 0 48 48" className="h-10 w-10">
          <circle cx="24" cy="24" r="13" {...common} />
          <path d="M18 24 q3 -5 6 0 q3 5 6 0" {...common} />
        </svg>
      )
    case 'line': // опора ВЛ
      return (
        <svg viewBox="0 0 48 48" className="h-10 w-10">
          <line x1="8" y1="16" x2="40" y2="16" {...common} />
          <line x1="24" y1="16" x2="24" y2="42" {...common} />
          <line x1="14" y1="24" x2="34" y2="24" {...common} strokeWidth={1} />
        </svg>
      )
    case 'ct': // трансформатор тока
      return (
        <svg viewBox="0 0 48 48" className="h-10 w-10">
          <circle cx="24" cy="17" r="6" {...common} />
          <circle cx="24" cy="31" r="6" {...common} />
          <line x1="24" y1="4" x2="24" y2="11" {...common} />
          <line x1="24" y1="37" x2="24" y2="44" {...common} />
        </svg>
      )
    case 'arrester': // ОПН
      return (
        <svg viewBox="0 0 48 48" className="h-10 w-10">
          <line x1="24" y1="4" x2="24" y2="18" {...common} />
          <line x1="16" y1="22" x2="32" y2="22" {...common} strokeWidth={2.4} />
          <line x1="24" y1="26" x2="24" y2="40" {...common} />
          <line x1="18" y1="40" x2="30" y2="40" {...common} />
          <line x1="17" y1="15" x2="31" y2="15" {...common} strokeWidth={1} strokeDasharray="2 2" />
        </svg>
      )
    default: // нагрузка / электроприёмник
      return (
        <svg viewBox="0 0 48 48" className="h-10 w-10">
          <circle cx="24" cy="24" r="13" {...common} />
          <text x="24" y="29" textAnchor="middle" fontSize="13" fill={stroke} stroke="none">
            M
          </text>
        </svg>
      )
  }
}

/** Рамка листа со штампом (как в ГОСТ-чертеже). */
export function SchemaFrameOverlay({
  frame,
  compact,
}: {
  frame: SchemaFrame
  compact: boolean
}) {
  const rows: Array<[string, string]> = [
    [frame.organization, frame.department],
    [frame.object_name, `${frame.sheet} · масштаб ${frame.scale}`],
    [
      `Разработал: ${frame.developed_by || '—'}`,
      `Проверил: ${frame.checked_by || '—'}`,
    ],
    [`Утвердил: ${frame.approved_by || '—'}`, frame.date],
  ]

  return (
    <div className="pointer-events-none absolute inset-3 z-[5] border-2 border-ink2/50">
      <div className="absolute inset-1 border border-ink2/25" />
      <div
        className={`absolute bottom-1 right-1 border border-ink2/50 bg-bg/80 ${
          compact ? 'w-[240px] text-[7px]' : 'w-[360px] text-[10px]'
        }`}
      >
        {rows.map((row, index) => (
          <div key={index} className="grid grid-cols-2 border-b border-ink2/25 last:border-b-0">
            <div className="border-r border-ink2/25 px-1.5 py-1 text-ink2">{row[0]}</div>
            <div className="px-1.5 py-1 text-ink3">{row[1]}</div>
          </div>
        ))}
      </div>
      <div className="absolute left-2 top-2 text-[10px] text-ink3">
        {frame.sheet_format} · {frame.organization}
      </div>
    </div>
  )
}
