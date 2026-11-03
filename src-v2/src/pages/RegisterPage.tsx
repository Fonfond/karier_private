import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { Alert, Field } from '../components/ui'
import { ApiError, api } from '../lib/api'

type Step = 1 | 2 | 3

interface StartResult {
  delivery: string
  delivery_target: string | null
  expires_in: number
  next_step: string
  debug_code: string | null
}

const deliveryLabel: Record<string, string> = {
  telegram: 'Telegram',
  email: 'e-mail',
  manual: 'администратора',
}

export function RegisterPage() {
  const navigate = useNavigate()
  const { applyUser } = useAuth()
  const [step, setStep] = useState<Step>(1)
  const [tabNo, setTabNo] = useState('')
  const [start, setStart] = useState<StartResult | null>(null)
  const [code, setCode] = useState('')
  const [setupToken, setSetupToken] = useState<string | null>(null)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const requestCode = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const data = await api.registerStart(tabNo.trim())
      if (data.next_step === 'already_registered') {
        setError('Этот табельный уже зарегистрирован. Войдите с паролем или обратитесь к администратору.')
        return
      }
      setStart(data)
      setStep(2)
      setInfo(`Код отправлен в ${deliveryLabel[data.delivery] ?? data.delivery}. Действует ${Math.round(data.expires_in / 60)} минут.`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось отправить код')
    } finally {
      setBusy(false)
    }
  }

  const checkCode = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const data = await api.registerVerify(tabNo.trim(), code.trim())
      setSetupToken(data.setup_token)
      setInfo(null)
      setStep(3)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось проверить код')
    } finally {
      setBusy(false)
    }
  }

  const savePassword = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    if (password !== confirm) {
      setError('Пароли не совпадают')
      return
    }
    if (!setupToken) return
    setBusy(true)
    try {
      const pair = await api.registerComplete(setupToken, password)
      applyUser(pair.user)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось установить пароль')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-[440px]">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-accent/15 text-2xl">
            🪪
          </div>
          <h1 className="text-[20px] font-semibold">Первая регистрация</h1>
          <p className="mt-1 text-[13px] text-ink2">
            Только для сотрудников, заведённых администратором
          </p>
        </div>

        <div className="mb-5 flex items-center justify-center gap-2">
          {[1, 2, 3].map((n) => (
            <div
              key={n}
              className={`h-1.5 w-12 rounded-full ${n <= step ? 'bg-accent' : 'bg-line'}`}
              aria-hidden
            />
          ))}
        </div>

        <div className="card space-y-4">
          {error ? <Alert kind="error">{error}</Alert> : null}
          {info && !error ? <Alert kind="info">{info}</Alert> : null}

          {step === 1 ? (
            <form onSubmit={requestCode} className="space-y-4">
              <Field label="Табельный номер" hint="Тот, который выдал отдел кадров">
                <input
                  className="input input-mono"
                  inputMode="numeric"
                  autoFocus
                  value={tabNo}
                  onChange={(e) => setTabNo(e.target.value)}
                  placeholder="000000"
                  required
                />
              </Field>
              <button type="submit" className="btn-primary w-full" disabled={busy}>
                {busy ? 'Отправляем…' : 'Получить код'}
              </button>
            </form>
          ) : null}

          {step === 2 ? (
            <form onSubmit={checkCode} className="space-y-4">
              <Field
                label="Код из сообщения"
                hint={start?.debug_code ? `На стенде код: ${start.debug_code}` : '6 цифр, действует 10 минут'}
              >
                <input
                  className="input input-mono text-center text-[24px] tracking-[0.4em]"
                  inputMode="numeric"
                  autoFocus
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="000000"
                  required
                />
              </Field>
              <button type="submit" className="btn-primary w-full" disabled={busy || code.length < 6}>
                {busy ? 'Проверяем…' : 'Подтвердить'}
              </button>
              <button
                type="button"
                className="btn-ghost w-full"
                onClick={() => {
                  setStep(1)
                  setCode('')
                  setError(null)
                }}
              >
                Изменить табельный
              </button>
            </form>
          ) : null}

          {step === 3 ? (
            <form onSubmit={savePassword} className="space-y-4">
              <Field label="Пароль" hint="Минимум 10 символов, не из частых, без фамилии и табельного">
                <input
                  className="input"
                  type="password"
                  autoComplete="new-password"
                  autoFocus
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••"
                  required
                />
              </Field>
              <Field label="Повторите пароль">
                <input
                  className="input"
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  placeholder="••••••••••"
                  required
                />
              </Field>
              <button type="submit" className="btn-primary w-full" disabled={busy}>
                {busy ? 'Сохраняем…' : 'Установить пароль и войти'}
              </button>
              <p className="text-[12px] text-ink3">
                После входа рекомендуем сразу подключить второй фактор в профиле — это займёт минуту.
              </p>
            </form>
          ) : null}

          <div className="border-t border-line pt-3 text-center text-[13px]">
            <Link to="/login" className="text-accent hover:underline">
              У меня уже есть пароль
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
