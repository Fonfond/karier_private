import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { Alert, Badge, PageTitle } from '../components/ui'
import { ApiError } from '../lib/api'
import type { DashboardSummary } from '../lib/dashboard'
import { dashboardApi, openExport } from '../lib/dashboard'
import { useInstallPrompt } from '../lib/useInstallPrompt'

const STATUS_LABEL: Record<string, string> = {
  on: 'под напряжением',
  off: 'обесточено',
  standby: 'резерв',
  maintenance: 'ремонт',
  decommissioned: 'списано',
}

const STATUS_COLOR: Record<string, string> = {
  on: '#2FBF71',
  off: '#6B7A8A',
  standby: '#3D8BFD',
  maintenance: '#F5A524',
  decommissioned: '#F2545B',
}

const SEVERITY_LABEL: Record<string, string> = {
  low: 'низкая',
  medium: 'средняя',
  high: 'высокая',
  critical: 'критичная',
}

const SEVERITY_COLOR: Record<string, string> = {
  low: '#6B7A8A',
  medium: '#4C9AFF',
  high: '#F5A524',
  critical: '#F2545B',
}

function Donut({ data }: { data: Array<{ label: string; value: number; color: string }> }) {
  const total = data.reduce((sum, item) => sum + item.value, 0) || 1
  const radius = 54
  const circumference = 2 * Math.PI * radius
  let offset = 0

  return (
    <div className="flex flex-wrap items-center gap-5">
      <svg viewBox="0 0 140 140" className="h-[150px] w-[150px] shrink-0">
        <circle cx="70" cy="70" r={radius} fill="none" stroke="#1B2733" strokeWidth="16" />
        {data.map((item) => {
          const length = (item.value / total) * circumference
          const dash = `${length} ${circumference - length}`
          const element = (
            <circle
              key={item.label}
              cx="70"
              cy="70"
              r={radius}
              fill="none"
              stroke={item.color}
              strokeWidth="16"
              strokeDasharray={dash}
              strokeDashoffset={-offset}
              transform="rotate(-90 70 70)"
              strokeLinecap="butt"
            />
          )
          offset += length
          return element
        })}
        <text x="70" y="66" textAnchor="middle" fontSize="22" fontWeight="600" fill="#E6EDF3">
          {total}
        </text>
        <text x="70" y="84" textAnchor="middle" fontSize="9" fill="#9FB0C0">
          объектов
        </text>
      </svg>
      <ul className="space-y-1.5 text-[12px]">
        {data.map((item) => (
          <li key={item.label} className="flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: item.color }} />
            <span className="text-ink2">{item.label}</span>
            <span className="text-ink3">{item.value}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Bars({ data }: { data: Array<{ label: string; value: number; color: string }> }) {
  const max = Math.max(1, ...data.map((item) => item.value))
  return (
    <ul className="space-y-2.5">
      {data.map((item) => (
        <li key={item.label}>
          <div className="mb-1 flex items-center justify-between text-[12px]">
            <span className="text-ink2">{item.label}</span>
            <span className="text-ink3">{item.value}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface2">
            <div
              className="h-full rounded-full"
              style={{ width: `${Math.max(4, (item.value / max) * 100)}%`, background: item.color }}
            />
          </div>
        </li>
      ))}
    </ul>
  )
}

export function DashboardPage() {
  const { user, can } = useAuth()
  const { canInstall, install } = useInstallPrompt()
  const [data, setData] = useState<DashboardSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setData(await dashboardApi.summary())
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить дашборд')
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 60000)
    return () => window.clearInterval(timer)
  }, [load])

  const exportExcel = async () => {
    setBusy(true)
    try {
      await openExport('assets')
    } finally {
      setBusy(false)
    }
  }

  if (error) {
    return (
      <div className="space-y-4">
        <PageTitle title="Дашборд" />
        <Alert kind="error">{error}</Alert>
      </div>
    )
  }

  if (!data) {
    return <div className="card text-[13px] text-ink3">Считаем показатели…</div>
  }

  const statusData = Object.entries(data.assets.by_status).map(([status, value]) => ({
    label: STATUS_LABEL[status] ?? status,
    value,
    color: STATUS_COLOR[status] ?? '#6B7A8A',
  }))
  const severityData = Object.entries(data.defects.by_severity).map(([severity, value]) => ({
    label: SEVERITY_LABEL[severity] ?? severity,
    value,
    color: SEVERITY_COLOR[severity] ?? '#4C9AFF',
  }))
  const critical = data.defects.by_severity.critical ?? 0
  const staleMobile = data.mobile.filter(
    (item) => item.days_since_move === null || item.days_since_move > 14,
  )

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageTitle
          title={`Здравствуйте, ${user?.full_name?.split(' ')[0] ?? 'коллега'}`}
          subtitle={`Сводка по карьеру на ${new Date(data.generated_at).toLocaleString('ru-RU', {
            dateStyle: 'short',
            timeStyle: 'short',
          })}`}
        />
        <div className="flex flex-wrap gap-2">
          {canInstall ? (
            <button type="button" className="btn-ghost h-10 px-3 text-[13px]" onClick={() => void install()}>
              📲 Установить приложение
            </button>
          ) : null}
          {can('report.export') ? (
            <button type="button" className="btn-ghost h-10 px-3 text-[13px]" disabled={busy} onClick={() => void exportExcel()}>
              ⬇ Excel: реестр
            </button>
          ) : null}
          <Link to="/map" className="btn-primary h-10 px-4 text-[13px]">
            Открыть карту
          </Link>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="card">
          <div className="text-[11px] uppercase tracking-wide text-ink3">Под напряжением</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-[28px] font-semibold text-ok">{data.assets.energized}</span>
            <span className="text-[12px] text-ink3">из {data.assets.total}</span>
          </div>
          <div className="mt-1 text-[12px] text-ink2">Обесточено: {data.assets.deenergized}</div>
        </div>

        <div className="card">
          <div className="text-[11px] uppercase tracking-wide text-ink3">Обнаруженные дефекты</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-[28px] font-semibold">{data.defects.open}</span>
            {critical > 0 ? <Badge tone="bad">критичных: {critical}</Badge> : null}
          </div>
          <div className="mt-1 text-[12px] text-ink2">Устранено за неделю: {data.defects.fixed_last_week}</div>
        </div>

        <div className="card">
          <div className="text-[11px] uppercase tracking-wide text-ink3">Обходы за неделю</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-[28px] font-semibold text-accent">{data.inspections.week}</span>
            <span className="text-[12px] text-ink3">проверок</span>
          </div>
          <div className="mt-1 text-[12px] text-ink2">
            Найдено дефектов: {data.inspections.week_defects} · отмечено объектов: {data.inspections.checked_items}
          </div>
        </div>

        <div className="card">
          <div className="text-[11px] uppercase tracking-wide text-ink3">Мачты Освещения Мобильные</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-[28px] font-semibold text-warm">{data.mobile.length}</span>
            <span className="text-[12px] text-ink3">мобильных</span>
          </div>
          <div className="mt-1 text-[12px] text-ink2">
            Без движения &gt; 14 дней: {staleMobile.length}
          </div>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-3 text-[15px] font-semibold">Статусы оборудования</h2>
          <Donut data={statusData} />
        </div>
        <div className="card">
          <h2 className="mb-3 text-[15px] font-semibold">Открытые дефекты по критичности</h2>
          {severityData.length ? <Bars data={severityData} /> : <p className="hint">Дефектов нет</p>}
          <div className="mt-3 border-t border-line pt-3 text-[12px] text-ink3">
            По категориям:{' '}
            {Object.entries(data.defects.by_category)
              .map(([category, value]) => `${category} — ${value}`)
              .join(', ') || '—'}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold">Мобильные объекты</h2>
          <Link to="/registry" className="text-[12px] text-accent">
            Весь реестр →
          </Link>
        </div>
        <div className="space-y-2">
          {data.mobile.map((item) => (
            <div key={item.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-line px-3 py-2">
              <span className="text-[14px]">🚚</span>
              <Link to={`/asset/${item.id}`} className="min-w-0 flex-1 truncate text-[13px] hover:text-accent">
                {item.code} · {item.name}
              </Link>
              <span className="text-[12px] text-ink2">
                {item.moved_at
                  ? `${new Date(item.moved_at).toLocaleDateString('ru-RU')} · ${item.days_since_move} дн. назад`
                  : 'перемещений не было'}
              </span>
              {item.days_since_move === null || item.days_since_move > 14 ? (
                <Badge tone="warm">проверить</Badge>
              ) : null}
            </div>
          ))}
          {data.mobile.length === 0 ? <p className="hint">Мобильных объектов нет</p> : null}
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Link to="/inspections" className="card text-[13px] hover:border-accent/60">
          📋 Мой обход
          <div className="mt-1 text-[11px] text-ink3">отметки и фото офлайн</div>
        </Link>
        <Link to="/defects" className="card text-[13px] hover:border-accent/60">
          ⚠️ Дефекты
          <div className="mt-1 text-[11px] text-ink3">закрытие с фото «после»</div>
        </Link>
        <Link to="/registry" className="card text-[13px] hover:border-accent/60">
          🗂 Реестр
          <div className="mt-1 text-[11px] text-ink3">таблица и выгрузка</div>
        </Link>
        <Link to="/sync" className="card text-[13px] hover:border-accent/60">
          ↻ Синхронизация
          <div className="mt-1 text-[11px] text-ink3">очередь и конфликты</div>
        </Link>
      </div>
    </div>
  )
}
