import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { Alert, Field } from '../components/ui'
import { ApiError } from '../lib/api'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [tabNo, setTabNo] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const mfa = await login(tabNo.trim(), password)
      if (mfa) {
        navigate('/mfa', {
          replace: true,
          state: { challenge: mfa.challenge_token, fullName: mfa.full_name },
        })
      } else {
        const from = (location.state as { from?: string } | null)?.from
        navigate(from && from !== '/login' ? from : '/', { replace: true })
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('Сервер недоступен. Проверьте сеть и повторите')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-[420px]">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-accent/15 text-2xl">
            ⚡
          </div>
          <h1 className="text-[22px] font-semibold">Карьер · Электроснабжение</h1>
          <p className="mt-1 text-[13px] text-ink2">
            Вход по табельному номеру. Доступ только для сотрудников участка.
          </p>
        </div>

        <form onSubmit={submit} className="card space-y-4">
          <Field label="Табельный номер" hint="Например, 000001">
            <input
              className="input input-mono"
              inputMode="numeric"
              autoComplete="username"
              autoFocus
              value={tabNo}
              onChange={(e) => setTabNo(e.target.value)}
              placeholder="000000"
              required
            />
          </Field>

          <Field label="Пароль">
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••"
              required
            />
          </Field>

          {error ? <Alert kind="error">{error}</Alert> : null}

          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? 'Проверяем…' : 'Войти'}
          </button>

          <div className="flex items-center justify-between pt-1 text-[13px]">
            <Link to="/register" className="text-accent hover:underline">
              Первая регистрация
            </Link>
            <span className="text-ink3">Забыли пароль — к администратору</span>
          </div>
        </form>

        {import.meta.env.DEV ? (
          <div className="mt-4 rounded-xl border border-line bg-surface1/60 px-4 py-3 text-[12px] text-ink3">
            <div className="mb-1 font-medium text-ink2">Тестовые учётные записи (dev)</div>
            <div className="font-mono">000001 / admin — администратор, 2FA выключена</div>
            <div className="font-mono">000002 / operator123 — оператор, 2FA включена</div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
