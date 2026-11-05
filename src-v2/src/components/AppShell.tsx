import { lazy, Suspense, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { useOutbox } from '../lib/useOutbox'
import { usePresentation } from '../lib/usePresentation'
import { Tour } from './Tour'
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
        <div className="mx-auto flex w-full max-w-[1400px] items-center gap-2 px-3 py-2.5 sm:gap-3 sm:px-4 sm:py-3">
          <div className="flex shrink-0 items-center gap-2">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent/15 text-lg">⚡</span>
            <div className="hidden leading-tight lg:block">
              <div className="text-[15px] font-semibold">Карьер</div>
              <div className="text-[11px] text-ink3">электроснабжение</div>
            </div>
          </div>

          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <NavLink to="/" className={link} end data-tour="dashboard">
              Дашборд
            </NavLink>
            <NavLink to="/map" className={link} data-tour="map">
              Карта
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

          <div className="flex shrink-0 items-center gap-2">
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
              className="btn-ghost h-9 w-9 p-0 text-[15px]"
              title="Сканировать QR"
              onClick={() => setScanOpen(true)}
            >
              ▣
            </button>

            <NavLink
              to="/sync"
              className={`hidden h-9 items-center gap-1.5 rounded-lg border px-2.5 text-[12px] sm:flex ${
                !online
                  ? 'border-warm/40 bg-warm/10 text-warm'
                  : pending > 0
                    ? 'border-accent/40 bg-accent/10 text-accent'
                    : 'border-line text-ink2'
              }`}
              title={online ? 'Синхронизация' : 'Нет сети'}
            >
              {syncing ? '↻ синхронизация' : online ? (pending > 0 ? `↑ ${pending}` : '✓ синхронно') : `офлайн · ${pending}`}
            </NavLink>

            <span className="hidden sm:inline-flex">
              {user?.mfa_enabled ? <Badge tone="ok">2FA</Badge> : <Badge tone="warm">без 2FA</Badge>}
            </span>
            <NavLink to="/profile" className="btn-ghost h-9 px-2.5 text-[12px]">
              {user?.tab_no}
            </NavLink>
            <button
              type="button"
              className="btn-ghost h-9 px-2.5 text-[12px]"
              onClick={handleLogout}
            >
              Выйти
            </button>
          </div>
        </div>
      </header>

      <main className={isMap ? 'relative min-h-0 flex-1' : 'mx-auto w-full max-w-6xl flex-1 px-4 py-6'}>
        <Outlet />
      </main>

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
