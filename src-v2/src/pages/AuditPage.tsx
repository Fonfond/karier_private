import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, PageTitle } from '../components/ui'
import { ApiError, api } from '../lib/api'
import type { AuditRecord } from '../lib/api'

const resultTone: Record<string, 'ok' | 'bad' | 'neutral'> = {
  ok: 'ok',
  denied: 'bad',
  error: 'neutral',
}

const actionLabel: Record<string, string> = {
  'auth.login.success': 'Вход выполнен',
  'auth.login.failed_password': 'Неверный пароль',
  'auth.login.mfa_required': 'Запрошен второй фактор',
  'auth.login.locked': 'Вход заблокирован',
  'auth.login.lockout': 'Блокировка после попыток',
  'auth.login.rate_limited': 'Лимит попыток входа',
  'auth.logout': 'Выход',
  'auth.refresh.reuse_detected': 'Повторное использование токена',
  'auth.register.code_sent': 'Код регистрации отправлен',
  'auth.register.code_verified': 'Код регистрации подтверждён',
  'auth.register.completed': 'Регистрация завершена',
  'auth.register.already_registered': 'Повторная регистрация',
  'auth.login.unknown_tab': 'Неизвестный табельный',
  'perm.denied': 'Отказ в доступе',
  'employee.created': 'Создан сотрудник',
  'employee.updated': 'Изменён сотрудник',
  'employee.blocked': 'Сотрудник заблокирован',
  'employee.unblocked': 'Сотрудник разблокирован',
  'employee.password_reset': 'Сброшен пароль',
  'auth.password_changed': 'Смена пароля',
  'auth.mfa.failed': 'Неверный код 2FA',
  'auth.mfa.recovery_code_used': 'Использован резервный код',
  'mfa.totp.enabled': 'Включена 2FA',
  'mfa.totp.disabled': 'Отключена 2FA',
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'medium' })
}

export function AuditPage() {
  const [items, setItems] = useState<AuditRecord[]>([])
  const [total, setTotal] = useState(0)
  const [result, setResult] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.audit({ limit: 100, result: result || undefined })
      setItems(data.items)
      setTotal(data.total)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить журнал')
    } finally {
      setLoading(false)
    }
  }, [result])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="space-y-6">
      <PageTitle
        title="Журнал действий"
        subtitle="Неизменяемый след: кто, что, когда, с какого устройства. Записи нельзя изменить или удалить"
      />

      <div className="flex flex-wrap items-center gap-3">
        <select className="input h-10 w-auto" value={result} onChange={(e) => setResult(e.target.value)}>
          <option value="">Все результаты</option>
          <option value="ok">Успешные</option>
          <option value="denied">Отказы</option>
          <option value="error">Ошибки</option>
        </select>
        <button type="button" className="btn-ghost h-10 px-4 text-[13px]" onClick={() => void load()}>
          {loading ? 'Обновляем…' : 'Обновить'}
        </button>
        <span className="text-[13px] text-ink3">всего записей: {total}</span>
      </div>

      {error ? <Alert kind="error">{error}</Alert> : null}

      <div className="card overflow-x-auto p-0">
        <table className="w-full min-w-[820px] text-left text-[13px]">
          <thead className="bg-surface2/60 text-[12px] uppercase tracking-wide text-ink3">
            <tr>
              <th className="px-4 py-3 font-medium">Время</th>
              <th className="px-4 py-3 font-medium">Кто</th>
              <th className="px-4 py-3 font-medium">Событие</th>
              <th className="px-4 py-3 font-medium">Объект</th>
              <th className="px-4 py-3 font-medium">Результат</th>
              <th className="px-4 py-3 font-medium">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((row) => (
              <tr key={row.id} className="align-top">
                <td className="whitespace-nowrap px-4 py-3 font-mono text-[12px] text-ink2">
                  {formatDate(row.at)}
                </td>
                <td className="px-4 py-3">
                  <div className="font-mono">{row.actor_tab_no ?? '—'}</div>
                  <div className="text-[12px] text-ink3">{row.actor_role ?? ''}</div>
                </td>
                <td className="px-4 py-3">
                  <div>{actionLabel[row.action] ?? row.action}</div>
                  {row.detail ? <div className="text-[12px] text-ink3">{row.detail}</div> : null}
                </td>
                <td className="px-4 py-3 text-[12px] text-ink2">
                  {row.entity ?? '—'}
                  {row.entity_id ? <div className="font-mono text-[11px] text-ink3">{row.entity_id.slice(0, 12)}…</div> : null}
                </td>
                <td className="px-4 py-3">
                  <Badge tone={resultTone[row.result] ?? 'neutral'}>{row.result}</Badge>
                </td>
                <td className="px-4 py-3 font-mono text-[12px] text-ink3">{row.ip ?? '—'}</td>
              </tr>
            ))}
            {items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-ink3">
                  Записей нет
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}
