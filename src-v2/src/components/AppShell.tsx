import { NavLink, Outlet, useNavigate } from 'react-router-dom'
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

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-xl px-3 py-2 text-[14px] transition ${
      isActive ? 'bg-surface2 text-ink' : 'text-ink2 hover:bg-surface2/60 hover:text-ink'
    }`

  return (
    <div className="min-h-screen bg-bg">
      <header className="sticky top-0 z-10 border-b border-line bg-bg/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3">
          <div className="mr-2 flex items-center gap-2">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-accent/15 text-lg">⚡</span>
            <div className="leading-tight">
              <div className="text-[15px] font-semibold">Карьер</div>
              <div className="text-[11px] text-ink3">электроснабжение</div>
            </div>
          </div>

          <nav className="flex flex-1 flex-wrap items-center gap-1">
            <NavLink to="/" className={link} end>
              Главная
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

          <div className="flex items-center gap-3">
            <div className="hidden text-right leading-tight sm:block">
              <div className="text-[13px] font-medium">{user?.full_name}</div>
              <div className="text-[11px] text-ink3">
                таб. {user?.tab_no} · {roleLabel[user?.role ?? ''] ?? user?.role}
              </div>
            </div>
            {user?.mfa_enabled ? <Badge tone="ok">2FA</Badge> : <Badge tone="warm">без 2FA</Badge>}
            <button type="button" className="btn-ghost h-10 px-3 text-[13px]" onClick={handleLogout}>
              Выйти
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
