import { lazy, Suspense, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { useOutbox } from '../lib/useOutbox'
import { usePresentation } from '../lib/usePresentation'
import { Tour } from './Tour'
import { BottomNav } from './BottomNav'
import { Badge } from './ui'

// Сканер тянет html5-qrcode (~300 КБ) — грузим только при открытии
const QrScanner = lazy(() =>
  import('./QrScanner').then((module) => ({ default: module.QrScanner })),
)

export function AppShell() {
  const { user, logout, can } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const isMap = location.pathname === '/map'
  const isSchema = new URLSearchParams(location.search).get('view') === 'schema'
  const { pending, online, syncing } = useOutbox()
  const { presentation, togglePresentation } = usePresentation()
  const [scanOpen, setScanOpen] = useState(false)

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const link = ({ isActive }: { isActive: boolean }) =>
    `shrink-0 rounded-xl px-2.5 py-2 text-[13px] transition sm:px-3 sm:text-[14px] ${
      isActive ? 'bg-surface2 text-ink' : 'text-ink2 hover:bg-surface2/60 hover:text-ink'
    }`

  return (
    <div className="flex min-h-[100dvh] flex-col bg-bg">
      <header className="sticky top-0 z-[1300] shrink-0 border-b border-line bg-bg/95 backdrop-blur">
        <div className="mx-auto flex w-full max-w-[1400px] flex-nowrap items-center gap-1.5 px-2 py-1.5 sm:gap-3 sm:px-4 sm:py-3">
          <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-xl bg-accent/15 text-base sm:h-9 sm:w-9 sm:text-lg">
              ⚡
            </span>
            <div className="leading-tight">
              <div className="text-[14px] font-semibold sm:text-[15px]">Карьер</div>
              <div className="hidden text-[11px] text-ink3 sm:block">электроснабжение</div>
            </div>
          </div>

          {/* 38a: на телефоне переключатель Карта/Схема сжат в шапку — отдельная
              строка фильтров на холсте больше не нужна. На десктопе он остаётся
              в панели над картой/схемой (md:hidden). */}
          {isMap ? (
            <div
              className="flex shrink-0 items-center rounded-full border border-line bg-bg/85 p-0.5 md:hidden"
              role="group"
              aria-label="Вид: карта или схема"
            >
              <button
                type="button"
                aria-pressed={!isSchema}
                className={`rounded-full px-2.5 py-1 text-[11px] ${
                  !isSchema ? 'bg-accent text-[#08131F]' : 'text-ink2'
                }`}
                onClick={() => navigate('/map')}
              >
                Карта
              </button>
              <button
                type="button"
                aria-pressed={isSchema}
                className={`rounded-full px-2.5 py-1 text-[11px] ${
                  isSchema ? 'bg-accent text-[#08131F]' : 'text-ink2'
                }`}
                onClick={() => navigate('/map?view=schema')}
              >
                Схема
              </button>
            </div>
          ) : null}

          <nav className="hidden min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden md:flex">
            <NavLink to="/" className={link} end data-tour="dashboard">
              Дашборд
            </NavLink>
            <NavLink to="/map" className={link} data-tour="map">
              Карта
            </NavLink>
            <NavLink to="/cables" className={link}>
              Кабели
            </NavLink>
            <NavLink to="/registry" className={link}>
              Реестр
            </NavLink>
            <NavLink to="/inspections" className={link} data-tour="inspections">
              Обход
            </NavLink>
            <NavLink to="/defects" className={link}>
              Дефекты
            </NavLink>
            {can('settings.edit') && (
              <NavLink to="/types" className={link}>
                Типы
              </NavLink>
            )}
            {can('employee.manage') && (
              <NavLink to="/employees" className={link}>
                Люди
              </NavLink>
            )}
            {can('audit.view') && (
              <NavLink to="/audit" className={link}>
                Журнал
              </NavLink>
            )}
          </nav>

          <div className="flex shrink-0 items-center gap-1 sm:gap-2">
            <button
              type="button"
              className={`hidden h-9 px-2.5 text-[12px] sm:inline-flex ${presentation ? 'btn-primary' : 'btn-ghost'}`}
              title="Режим презентации: крупнее интерфейс, скрыты админские кнопки"
              onClick={togglePresentation}
            >
              🎬
            </button>
            <button
              type="button"
              className="btn-ghost h-8 w-8 p-0 text-[14px] sm:h-9 sm:w-9 sm:text-[15px]"
              title="Сканировать QR"
              aria-label="Сканировать QR"
              onClick={() => setScanOpen(true)}
            >
              ▣
            </button>

            <NavLink
              to="/sync"
              className={`flex h-8 items-center gap-1.5 rounded-lg border px-2 text-[11px] sm:h-9 sm:px-2.5 sm:text-[12px] ${
                !online
                  ? 'border-warm/40 bg-warm/10 text-warm'
                  : pending > 0
                    ? 'border-accent/40 bg-accent/10 text-accent'
                    : 'border-line text-ink2'
              }`}
              title={online ? 'Синхронизация' : 'Нет сети'}
            >
              <span className="sm:hidden">{online ? (pending > 0 ? `↑${pending}` : '☁') : '⚡'}</span>
              <span className="hidden sm:inline">
                {syncing ? '↻ синхронизация' : online ? (pending > 0 ? `↑ ${pending}` : '✓ синхронно') : `офлайн · ${pending}`}
              </span>
            </NavLink>

            <span className="hidden md:inline-flex">
              {user?.mfa_enabled ? <Badge tone="ok">2FA</Badge> : <Badge tone="warm">без 2FA</Badge>}
            </span>
            <NavLink
              to="/profile"
              className="btn-ghost h-8 w-8 p-0 text-[10px] sm:h-9 sm:w-auto sm:px-2.5 sm:text-[12px]"
              title="Профиль (также в «Ещё»)"
            >
              {user?.tab_no?.slice(-2) ?? '👤'}
            </NavLink>
            <button
              type="button"
              className="btn-ghost hidden h-9 px-2.5 text-[12px] md:inline-flex"
              onClick={handleLogout}
            >
              Выйти
            </button>
          </div>
        </div>
      </header>

      <main
        style={isMap ? { paddingBottom: 'var(--bottom-nav)' } : undefined}
        className={
          isMap
            ? 'relative min-h-0 flex-1'
            : 'mx-auto w-full max-w-6xl flex-1 px-3 py-4 pb-nav sm:px-4 sm:py-6'
        }
      >
        <Outlet />
      </main>

      <BottomNav />

      <Tour />

      {scanOpen ? (
        <Suspense fallback={null}>
          <QrScanner
            open={scanOpen}
            onClose={() => setScanOpen(false)}
            onScanned={(assetId) => {
              setScanOpen(false)
              navigate(`/asset/${assetId}`)
            }}
          />
        </Suspense>
      ) : null}
    </div>
  )
}
