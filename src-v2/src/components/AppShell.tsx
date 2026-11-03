import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { Badge } from './ui'

const roleLabel: Record<string, string> = {
  admin: 'Администратор',
  operator: 'Оператор',
  viewer: 'Наблюдатель',
  contractor: 'Подрядчик',
}

export function AppShell() {
  const { user, logout, can } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const isMap = location.pathname === '/'

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
        <div className="mx-auto flex w-full max-w-6xl items-center gap-2 px-3 py-2.5 sm:gap-3 sm:px-4 sm:py-3">
          <div className="flex shrink-0 items-center gap-2">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent/15 text-lg">⚡</span>
            <div className="hidden leading-tight md:block">
              <div className="text-[15px] font-semibold">Карьер</div>
              <div className="text-[11px] text-ink3">электроснабжение</div>
            </div>
          </div>

          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <NavLink to="/" className={link} end>
              Карта
            </NavLink>
            <NavLink to="/status" className={link}>
              Статус
            </NavLink>
            {can('employee.manage') && (
              <NavLink to="/employees" className={link}>
                Сотрудники
              </NavLink>
            )}
            {can('audit.view') && (
              <NavLink to="/audit" className={link}>
                Журнал
              </NavLink>
            )}
            <NavLink to="/profile" className={link}>
              Профиль
            </NavLink>
          </nav>

          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <div className="hidden text-right leading-tight lg:block">
              <div className="text-[13px] font-medium">{user?.full_name}</div>
              <div className="text-[11px] text-ink3">
                таб. {user?.tab_no} · {roleLabel[user?.role ?? ''] ?? user?.role}
              </div>
            </div>
            <span className="hidden sm:inline-flex">
              {user?.mfa_enabled ? <Badge tone="ok">2FA</Badge> : <Badge tone="warm">без 2FA</Badge>}
            </span>
            <button
              type="button"
              className="btn-ghost h-9 px-2.5 text-[12px] sm:h-10 sm:px-3 sm:text-[13px]"
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
    </div>
  )
}
