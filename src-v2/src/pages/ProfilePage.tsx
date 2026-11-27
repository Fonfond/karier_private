import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { Alert, Badge, ConfirmDialog, Field, PageTitle } from '../components/ui'
import { ApiError, api } from '../lib/api'

interface SessionRow {
  id: string
  created_at: string
  last_seen_at: string | null
  ip: string | null
  user_agent: string | null
  current: boolean
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

export function ProfilePage() {
  const { user, logout, refreshUser } = useAuth()
  const navigate = useNavigate()

  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordInfo, setPasswordInfo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [enrollSecret, setEnrollSecret] = useState<string | null>(null)
  const [enrollQr, setEnrollQr] = useState<string | null>(null)
  const [totpCode, setTotpCode] = useState('')
  const [recovery, setRecovery] = useState<string[] | null>(null)
  const [mfaError, setMfaError] = useState<string | null>(null)
  const [sessions, setSessions] = useState<SessionRow[]>([])
  const [revokeTarget, setRevokeTarget] = useState<SessionRow | null>(null)
  const [revokeBusy, setRevokeBusy] = useState(false)
  const [sessionError, setSessionError] = useState<string | null>(null)

  useEffect(() => {
    api.sessions().then(setSessions).catch(() => setSessions([]))
  }, [])

  const changePassword = async (event: FormEvent) => {
    event.preventDefault()
    setPasswordError(null)
    setPasswordInfo(null)
    if (next !== confirm) {
      setPasswordError('Пароли не совпадают')
      return
    }
    setBusy(true)
    try {
      await api.changePassword(current, next)
      await logout()
      navigate('/login', { replace: true })
    } catch (err) {
      setPasswordError(err instanceof ApiError ? err.message : 'Не удалось сменить пароль')
    } finally {
      setBusy(false)
    }
  }

  const startEnroll = async () => {
    setMfaError(null)
    try {
      const data = await api.totpEnroll()
      setEnrollSecret(data.secret)
      setEnrollQr(data.qr_svg)
    } catch (err) {
      setMfaError(err instanceof ApiError ? err.message : 'Не удалось начать подключение 2FA')
    }
  }

  const confirmEnroll = async (event: FormEvent) => {
    event.preventDefault()
    setMfaError(null)
    try {
      const data = await api.totpConfirm(totpCode.trim())
      setRecovery(data.codes)
      setEnrollQr(null)
      setEnrollSecret(null)
      setTotpCode('')
      await refreshUser()
    } catch (err) {
      setMfaError(err instanceof ApiError ? err.message : 'Неверный код')
    }
  }

  const revoke = async (session: SessionRow) => {
    setRevokeBusy(true)
    setSessionError(null)
    try {
      await api.revokeSession(session.id)
      setSessions(await api.sessions())
      setRevokeTarget(null)
    } catch (err) {
      setSessionError(err instanceof ApiError ? err.message : 'Не удалось отозвать сессию')
    } finally {
      setRevokeBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageTitle title="Профиль" subtitle="Пароль, второй фактор и активные устройства" />

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <h2 className="mb-3 text-[15px] font-semibold">Данные сотрудника</h2>
          <dl className="space-y-2 text-[14px]">
            <div className="flex justify-between gap-4">
              <dt className="text-ink2">ФИО</dt>
              <dd className="text-right">{user?.full_name}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink2">Табельный</dt>
              <dd className="font-mono">{user?.tab_no}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink2">Должность</dt>
              <dd className="text-right">{user?.position ?? '—'}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink2">Последний вход</dt>
              <dd>{formatDate(user?.last_login_at ?? null)}</dd>
            </div>
          </dl>
        </div>

        <div className="card">
          <h2 className="mb-3 text-[15px] font-semibold">Смена пароля</h2>
          <form onSubmit={changePassword} className="space-y-3">
            <Field label="Текущий пароль">
              <input
                className="input"
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                required
              />
            </Field>
            <Field label="Новый пароль" hint="Минимум 10 символов">
              <input
                className="input"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                required
              />
            </Field>
            <Field label="Повторите новый пароль">
              <input
                className="input"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
              />
            </Field>
            {passwordError ? <Alert kind="error">{passwordError}</Alert> : null}
            {passwordInfo ? <Alert kind="success">{passwordInfo}</Alert> : null}
            <button type="submit" className="btn-primary w-full" disabled={busy}>
              {busy ? 'Сохраняем…' : 'Сменить пароль'}
            </button>
            <p className="text-[12px] text-ink3">
              После смены все сессии отзываются, потребуется войти заново.
            </p>
          </form>
        </div>
      </div>

      <div className="card">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-[15px] font-semibold">Второй фактор (TOTP)</h2>
          {user?.mfa_enabled ? <Badge tone="ok">подключён</Badge> : <Badge tone="warm">не подключён</Badge>}
        </div>

        {user?.mfa_enabled ? (
          <p className="hint">
            Вход подтверждается кодом из приложения-аутентификатора. Резервные коды были показаны при
            подключении — храните их отдельно от телефона.
          </p>
        ) : (
          <>
            <p className="hint mb-3">
              Рекомендуется всем: код считается на телефоне, работает без интернета. Подойдёт Google
              Authenticator, Aegis, 1Password.
            </p>
            {!enrollQr ? (
              <button type="button" className="btn-primary" onClick={startEnroll}>
                Подключить 2FA
              </button>
            ) : (
              <form onSubmit={confirmEnroll} className="space-y-4">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
                  <img
                    src={enrollQr}
                    alt="QR-код для добавления в аутентификатор"
                    className="h-[180px] w-[180px] rounded-xl bg-white p-2"
                  />
                  <div className="space-y-2 text-[13px]">
                    <p className="text-ink2">1. Откройте приложение и отсканируйте QR.</p>
                    <p className="text-ink2">2. Если камера недоступна, введите ключ вручную:</p>
                    <code className="block break-all rounded-lg bg-surface2 px-3 py-2 font-mono text-[12px]">
                      {enrollSecret}
                    </code>
                  </div>
                </div>
                <Field label="3. Введите код из приложения">
                  <input
                    className="input input-mono max-w-[220px] text-center text-[22px] tracking-[0.35em]"
                    inputMode="numeric"
                    maxLength={6}
                    value={totpCode}
                    onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    placeholder="000000"
                  />
                </Field>
                {mfaError ? <Alert kind="error">{mfaError}</Alert> : null}
                <button type="submit" className="btn-primary" disabled={totpCode.length < 6}>
                  Включить 2FA
                </button>
              </form>
            )}
          </>
        )}

        {recovery ? (
          <div className="mt-4 space-y-2">
            <Alert kind="success">2FA включена. Сохраните резервные коды — они больше не покажутся.</Alert>
            <div className="grid grid-cols-2 gap-2 rounded-xl border border-line bg-surface2 p-4 font-mono text-[13px] sm:grid-cols-5">
              {recovery.map((value) => (
                <span key={value}>{value}</span>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      <div className="card">
        <h2 className="mb-3 text-[15px] font-semibold">Активные устройства</h2>
        {sessionError ? (
          <div className="mb-3">
            <Alert kind="error">{sessionError}</Alert>
          </div>
        ) : null}
        {sessions.length === 0 ? (
          <p className="hint">Нет данных</p>
        ) : (
          <ul className="divide-y divide-line">
            {sessions.map((session) => (
              <li key={session.id} className="flex items-center justify-between gap-3 py-3 text-[13px]">
                <div className="min-w-0">
                  <div className="truncate">{session.user_agent ?? 'Неизвестное устройство'}</div>
                  <div className="text-[12px] text-ink3">
                    {session.ip ?? '—'} · вход {formatDate(session.created_at)}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {session.current ? <Badge tone="accent">это устройство</Badge> : null}
                  {!session.current ? (
                    <button
                      type="button"
                      className="btn-danger h-9 px-3 text-[12px]"
                      onClick={() => setRevokeTarget(session)}
                    >
                      Отозвать
                    </button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <ConfirmDialog
        open={Boolean(revokeTarget)}
        title="Отозвать сессию?"
        message={
          revokeTarget
            ? `Устройство «${revokeTarget.user_agent ?? 'неизвестное'}» (${revokeTarget.ip ?? 'IP неизвестен'}) будет разлогинено. Понадобится повторный вход.`
            : undefined
        }
        confirmLabel="Отозвать"
        busy={revokeBusy}
        onConfirm={() => (revokeTarget ? revoke(revokeTarget) : undefined)}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  )
}
