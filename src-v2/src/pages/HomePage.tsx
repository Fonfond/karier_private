import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { Badge, PageTitle } from '../components/ui'

const roleLabel: Record<string, string> = {
  admin: 'Администратор (инженер/диспетчер)',
  operator: 'Оператор (рабочий/обходчик)',
  viewer: 'Наблюдатель',
  contractor: 'Подрядчик',
}

const sprintOne = [
  'Закрытая регистрация по табельному номеру',
  'Пароль Argon2id, блокировка после 5 попыток',
  'Второй фактор TOTP и резервные коды',
  'Роли и права: сервер проверяет каждое действие',
  'Журнал аудита: кто, что, когда, откуда',
  'Сессии, refresh-токены, отзыв доступа',
]

export function HomePage() {
  const { user, can } = useAuth()

  return (
    <div className="space-y-6">
      <PageTitle
        title={`Здравствуйте, ${user?.full_name?.split(' ')[0] ?? 'коллега'}`}
        subtitle="Спринт 1 «Доступ, роли, аудит» — готов. Следующий шаг: реестр объектов и карта."
      />

      {user?.must_change_password ? (
        <div className="rounded-card border border-warm/40 bg-warm/10 p-4 text-[14px] text-warm">
          Пароль временный — его выдал администратор.{' '}
          <Link to="/profile" className="underline">
            Смените пароль
          </Link>{' '}
          перед началом работы.
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="card">
          <h2 className="mb-3 text-[15px] font-semibold">Ваш доступ</h2>
          <dl className="space-y-2 text-[14px]">
            <div className="flex justify-between gap-4">
              <dt className="text-ink2">Табельный</dt>
              <dd className="font-mono">{user?.tab_no}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink2">Роль</dt>
              <dd>{roleLabel[user?.role ?? ''] ?? user?.role}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink2">Права</dt>
              <dd>{user?.permissions.length ?? 0} разрешений</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink2">Второй фактор</dt>
              <dd>
                {user?.mfa_enabled ? <Badge tone="ok">подключён</Badge> : <Badge tone="warm">не подключён</Badge>}
              </dd>
            </div>
          </dl>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link to="/profile" className="btn-ghost h-10 px-3 text-[13px]">
              Профиль и 2FA
            </Link>
            {can('employee.manage') ? (
              <Link to="/employees" className="btn-ghost h-10 px-3 text-[13px]">
                Сотрудники
              </Link>
            ) : null}
            {can('audit.view') ? (
              <Link to="/audit" className="btn-ghost h-10 px-3 text-[13px]">
                Журнал действий
              </Link>
            ) : null}
          </div>
        </div>

        <div className="card">
          <h2 className="mb-3 text-[15px] font-semibold">Что уже работает</h2>
          <ul className="space-y-2 text-[13px] text-ink2">
            {sprintOne.map((item) => (
              <li key={item} className="flex gap-2">
                <span className="text-ok">✓</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="card">
        <h2 className="mb-1 text-[15px] font-semibold">Дальше по плану</h2>
        <p className="hint">
          Спринт 2 — реестр объектов (подстанции, БКРУ, КСР, ЯКУ/ЯКУ-1Т, КТП, ДМО, ДМП, БМП, генераторы,
          ЭКГ, кабели) и карта карьера с привязкой подложки. Спринт 3 — топология питания и редактор схемы.
        </p>
      </div>
    </div>
  )
}
