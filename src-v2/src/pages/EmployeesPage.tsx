import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Alert, Badge, Field, PageTitle } from '../components/ui'
import { ApiError, api } from '../lib/api'
import type { Employee } from '../lib/api'

const roleOptions = [
  { value: 'operator', label: 'Оператор' },
  { value: 'admin', label: 'Администратор' },
  { value: 'viewer', label: 'Наблюдатель' },
  { value: 'contractor', label: 'Подрядчик' },
]

const statusTone: Record<string, 'ok' | 'bad' | 'warm' | 'neutral'> = {
  active: 'ok',
  blocked: 'bad',
  dismissed: 'neutral',
}

const statusLabel: Record<string, string> = {
  active: 'активен',
  blocked: 'заблокирован',
  dismissed: 'уволен',
}

export function EmployeesPage() {
  const [items, setItems] = useState<Employee[]>([])
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [tabNo, setTabNo] = useState('')
  const [fullName, setFullName] = useState('')
  const [position, setPosition] = useState('')
  const [role, setRole] = useState('operator')
  const [otpChannel, setOtpChannel] = useState('telegram')
  const [telegramId, setTelegramId] = useState('')

  const [editing, setEditing] = useState<Employee | null>(null)
  const [editForm, setEditForm] = useState({ full_name: '', position: '', role: 'operator', phone_e164: '' })

  const openEditor = (employee: Employee) => {
    setEditing(employee)
    setEditForm({
      full_name: employee.full_name,
      position: employee.position ?? '',
      role: employee.role,
      phone_e164: employee.phone_e164 ?? '',
    })
  }

  const saveEditor = async () => {
    if (!editing) return
    setBusy(true)
    setError(null)
    try {
      await api.updateEmployee(editing.id, {
        full_name: editForm.full_name.trim(),
        position: editForm.position.trim() || null,
        role: editForm.role,
        phone_e164: editForm.phone_e164.trim() || null,
      })
      setNotice(`Карточка ${editing.tab_no} обновлена`)
      setEditing(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить карточку')
    } finally {
      setBusy(false)
    }
  }

  const removePermanently = async (employee: Employee) => {
    if (
      !window.confirm(
        `Удалить ${employee.full_name} (таб. ${employee.tab_no}) НАВСЕГДА? Действие необратимо.`,
      )
    ) {
      return
    }
    setError(null)
    try {
      await api.deleteEmployeePermanent(employee.id)
      setNotice(`Сотрудник ${employee.tab_no} удалён из базы`)
      await load()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setNotice(
          'У сотрудника есть действия в журнале — удаление стёрло бы авторство. Используйте «Уволить».',
        )
        setError(err.message)
      } else {
        setError(err instanceof ApiError ? err.message : 'Не удалось удалить сотрудника')
      }
    }
  }

  const dismiss = async (employee: Employee) => {
    if (
      !window.confirm(
        `Уволить ${employee.full_name} (таб. ${employee.tab_no})? Учётная запись будет заархивирована, вход заблокирован.`,
      )
    ) {
      return
    }
    setError(null)
    try {
      await api.dismissEmployee(employee.id)
      setNotice(`Сотрудник ${employee.tab_no} уволен, сессии отозваны`)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось уволить сотрудника')
    }
  }

  const load = useCallback(async () => {
    try {
      const data = await api.employees(search)
      setItems(data.items)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить список')
    }
  }, [search])

  useEffect(() => {
    void load()
  }, [load])

  const create = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setNotice(null)
    setBusy(true)
    try {
      const created = await api.createEmployee({
        tab_no: tabNo.trim(),
        full_name: fullName.trim(),
        role,
        position: position.trim() || undefined,
        otp_channel: otpChannel,
        telegram_id: telegramId ? Number(telegramId) : null,
      })
      setNotice(`Сотрудник ${created.tab_no} заведён. Отправьте ему код первичной регистрации.`)
      setTabNo('')
      setFullName('')
      setPosition('')
      setTelegramId('')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать сотрудника')
    } finally {
      setBusy(false)
    }
  }

  const act = async (action: 'block' | 'unblock' | 'reset' | 'invite', employee: Employee) => {
    setError(null)
    setNotice(null)
    try {
      if (action === 'block') await api.blockEmployee(employee.id)
      if (action === 'unblock') await api.unblockEmployee(employee.id)
      if (action === 'reset') {
        const data = await api.resetPassword(employee.id)
        setNotice(`Временный пароль для ${employee.tab_no}: ${data.temp_password}`)
      }
      if (action === 'invite') {
        const data = await api.resendInvite(employee.id)
        setNotice(
          `Код отправлен (${data.delivery})${data.debug_code ? `, код на стенде: ${data.debug_code}` : ''}`,
        )
      }
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Действие не выполнено')
    }
  }

  return (
    <div className="space-y-6">
      <PageTitle
        title="Сотрудники"
        subtitle="Закрытый справочник: войти может только тот, кто здесь заведён"
      />

      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      <form onSubmit={create} className="card grid gap-3 md:grid-cols-6">
        <div className="md:col-span-1">
          <Field label="Табельный">
            <input
              className="input input-mono"
              value={tabNo}
              onChange={(e) => setTabNo(e.target.value)}
              placeholder="000005"
              required
            />
          </Field>
        </div>
        <div className="md:col-span-2">
          <Field label="ФИО">
            <input
              className="input"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Иванов Иван Иванович"
              required
            />
          </Field>
        </div>
        <div className="md:col-span-1">
          <Field label="Должность">
            <input
              className="input"
              value={position}
              onChange={(e) => setPosition(e.target.value)}
              placeholder="Электромонтёр"
            />
          </Field>
        </div>
        <div className="md:col-span-1">
          <Field label="Роль">
            <select className="input" value={role} onChange={(e) => setRole(e.target.value)}>
              {roleOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="md:col-span-1">
          <Field label="Канал кода">
            <select className="input" value={otpChannel} onChange={(e) => setOtpChannel(e.target.value)}>
              <option value="telegram">Telegram</option>
              <option value="email">E-mail</option>
              <option value="manual">Вручную</option>
            </select>
          </Field>
        </div>
        <div className="md:col-span-2">
          <Field label="Telegram ID" hint="Куда отправлять код (для стенда необязательно)">
            <input
              className="input font-mono"
              value={telegramId}
              onChange={(e) => setTelegramId(e.target.value.replace(/\D/g, ''))}
              placeholder="100000005"
            />
          </Field>
        </div>
        <div className="flex items-end md:col-span-4">
          <button type="submit" className="btn-primary w-full md:w-auto md:px-6" disabled={busy}>
            {busy ? 'Сохраняем…' : 'Завести сотрудника'}
          </button>
        </div>
      </form>

      <div className="card">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[15px] font-semibold">Список ({items.length})</h2>
          <input
            className="input h-10 w-full max-w-[260px]"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск по ФИО или табельному"
          />
        </div>

        <div className="-mx-2 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-[13px]">
            <thead className="text-[12px] uppercase tracking-wide text-ink3">
              <tr>
                <th className="px-2 py-2 font-medium">Таб.</th>
                <th className="px-2 py-2 font-medium">ФИО</th>
                <th className="px-2 py-2 font-medium">Роль</th>
                <th className="px-2 py-2 font-medium">Статус</th>
                <th className="px-2 py-2 font-medium">Доступ</th>
                <th className="px-2 py-2 font-medium">Действия</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {items.map((employee) => (
                <tr key={employee.id}>
                  <td className="px-2 py-3 font-mono">{employee.tab_no}</td>
                  <td className="px-2 py-3">
                    <div>{employee.full_name}</div>
                    <div className="text-[12px] text-ink3">{employee.position ?? '—'}</div>
                  </td>
                  <td className="px-2 py-3">{employee.role}</td>
                  <td className="px-2 py-3">
                    <Badge tone={statusTone[employee.status] ?? 'neutral'}>
                      {statusLabel[employee.status] ?? employee.status}
                    </Badge>
                  </td>
                  <td className="px-2 py-3">
                    <div className="flex flex-col gap-1">
                      <span className={employee.has_credentials ? 'text-ink2' : 'text-warm'}>
                        {employee.has_credentials ? 'пароль установлен' : 'ждёт регистрации'}
                      </span>
                      {employee.mfa_enabled ? <span className="text-ok">2FA</span> : null}
                    </div>
                  </td>
                  <td className="px-2 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      {employee.status === 'active' ? (
                        <button
                          type="button"
                          className="btn-danger h-8 px-2.5 text-[12px]"
                          onClick={() => void act('block', employee)}
                        >
                          Блок
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn-ghost h-8 px-2.5 text-[12px]"
                          onClick={() => void act('unblock', employee)}
                        >
                          Разблокировать
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn-ghost h-8 px-2.5 text-[12px]"
                        title="Изменить ФИО, должность, роль"
                        onClick={() => openEditor(employee)}
                      >
                        ✎
                      </button>
                      {employee.status !== 'dismissed' ? (
                        <button
                          type="button"
                          className="btn-ghost h-8 px-2.5 text-[12px] text-warm"
                          title="Уволить (архивировать)"
                          onClick={() => void dismiss(employee)}
                        >
                          Уволить
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="btn-ghost h-8 px-2.5 text-[12px] text-bad"
                        title="Удалить навсегда (только без истории)"
                        onClick={() => void removePermanently(employee)}
                      >
                        🗑
                      </button>
                      <button
                        type="button"
                        className="btn-ghost h-8 px-2.5 text-[12px]"
                        onClick={() => void act('reset', employee)}
                      >
                        Сброс пароля
                      </button>
                      {!employee.has_credentials ? (
                        <button
                          type="button"
                          className="btn-ghost h-8 px-2.5 text-[12px]"
                          onClick={() => void act('invite', employee)}
                        >
                          Код
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-2 py-6 text-center text-ink3">
                    Сотрудников нет
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>

      {editing ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center sm:p-4">
          <div className="w-full max-w-lg rounded-t-2xl border border-line bg-surface1 p-4 sm:rounded-2xl">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[16px] font-semibold">Карточка {editing.tab_no}</h2>
              <button type="button" className="btn-ghost h-9 px-3 text-[12px]" onClick={() => setEditing(null)}>
                Закрыть
              </button>
            </div>
            <div className="space-y-3">
              <Field label="ФИО">
                <input
                  className="input"
                  value={editForm.full_name}
                  onChange={(e) => setEditForm({ ...editForm, full_name: e.target.value })}
                />
              </Field>
              <Field label="Должность">
                <input
                  className="input"
                  value={editForm.position}
                  onChange={(e) => setEditForm({ ...editForm, position: e.target.value })}
                  placeholder="Старший электромонтёр"
                />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Роль">
                  <select
                    className="input"
                    value={editForm.role}
                    onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
                  >
                    {roleOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Телефон">
                  <input
                    className="input"
                    value={editForm.phone_e164}
                    onChange={(e) => setEditForm({ ...editForm, phone_e164: e.target.value })}
                    placeholder="+79000000000"
                  />
                </Field>
              </div>
            </div>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                className="btn-primary px-5"
                disabled={busy || editForm.full_name.trim().length < 3}
                onClick={() => void saveEditor()}
              >
                {busy ? 'Сохраняем…' : 'Сохранить'}
              </button>
              <button type="button" className="btn-ghost" onClick={() => setEditing(null)}>
                Отмена
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
