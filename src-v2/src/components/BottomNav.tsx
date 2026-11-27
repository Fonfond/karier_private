import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useAuth } from '../auth/AuthProvider'

interface Tab {
  to: string
  label: string
  icon: string
  match?: (path: string) => boolean
}

const TABS: Tab[] = [
  { to: '/', label: 'Главная', icon: '🏠', match: (path) => path === '/' },
  { to: '/map', label: 'Карта', icon: '🗺', match: (path) => path === '/map' },
  { to: '/map?view=schema', label: 'Схема', icon: '⚡', match: (path) => path.startsWith('/map/schema') },
  { to: '/inspections', label: 'Обходы', icon: '📋', match: (path) => path.startsWith('/inspections') },
]

/** Нижняя навигация для телефона: 5 крупных целей в зоне большого пальца. */
export function BottomNav() {
  const { can } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [moreOpen, setMoreOpen] = useState(false)

  const isMap = location.pathname === '/map'
  const schemaView = new URLSearchParams(location.search).get('view') === 'schema'

  const more = [
    { to: '/registry', label: 'Реестр', icon: '🗂' },
    { to: '/cables', label: 'Кабели', icon: '〰' },
    { to: '/defects', label: 'Дефекты', icon: '⚠️' },
    can('settings.edit') ? { to: '/types', label: 'Типы', icon: '⚙️' } : null,
    can('employee.manage') ? { to: '/employees', label: 'Сотрудники', icon: '👷' } : null,
    can('audit.view') ? { to: '/audit', label: 'Журнал', icon: '📜' } : null,
    { to: '/sync', label: 'Синхронизация', icon: '↻' },
    { to: '/profile', label: 'Профиль', icon: '👤' },
  ].filter(Boolean) as Array<{ to: string; label: string; icon: string }>

  return (
    <>
      {moreOpen ? (
        <div className="fixed inset-0 z-[1400] md:hidden" onClick={() => setMoreOpen(false)}>
          <div className="absolute inset-0 bg-black/50" />
          <div
            className="absolute inset-x-2 bottom-[calc(70px+env(safe-area-inset-bottom))] rounded-2xl border border-line bg-surface1 p-2 shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            {more.map((item) => (
              <button
                key={item.to}
                type="button"
                className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-[15px] text-ink active:bg-surface2"
                onClick={() => {
                  setMoreOpen(false)
                  navigate(item.to)
                }}
              >
                <span className="text-lg">{item.icon}</span>
                {item.label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <nav
        className="fixed inset-x-0 bottom-0 z-[1300] border-t border-line bg-surface1/98 backdrop-blur md:hidden"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)', height: 'var(--bottom-nav-bar)' }}
      >
        <div className="grid grid-cols-5">
          {TABS.map((tab) => {
            const active =
              tab.label === 'Схема'
                ? isMap && schemaView
                : tab.label === 'Карта'
                  ? isMap && !schemaView
                  : tab.match
                    ? tab.match(location.pathname)
                    : false
            return (
              <NavLink
                key={tab.label}
                to={tab.to}
                className={`flex min-h-[56px] flex-col items-center justify-center gap-0.5 text-[11px] ${
                  active ? 'text-accent' : 'text-ink2'
                }`}
              >
                <span className="text-[20px] leading-none">{tab.icon}</span>
                {tab.label}
              </NavLink>
            )
          })}
          <button
            type="button"
            className={`flex min-h-[56px] flex-col items-center justify-center gap-0.5 text-[11px] ${
              moreOpen ? 'text-accent' : 'text-ink2'
            }`}
            onClick={() => setMoreOpen((prev) => !prev)}
          >
            <span className="text-[20px] leading-none">⋯</span>
            Ещё
          </button>
        </div>
      </nav>
    </>
  )
}
