import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { Alert } from '../components/ui'
import { ApiError } from '../lib/api'

interface MfaState {
  challenge?: string
  fullName?: string
}

export function MfaPage() {
  const { verifyMfa } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const state = (location.state as MfaState | null) ?? {}
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!state.challenge) navigate('/login', { replace: true })
    inputRef.current?.focus()
  }, [state.challenge, navigate])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!state.challenge) return
    setError(null)
    setBusy(true)
    try {
      await verifyMfa(state.challenge, code.trim())
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось подтвердить код')
      setCode('')
      inputRef.current?.focus()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-[420px]">
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-accent/15 text-2xl">
            🔐
          </div>
          <h1 className="text-[20px] font-semibold">Подтверждение входа</h1>
          <p className="mt-1 text-[13px] text-ink2">
            {state.fullName ? `${state.fullName}, введите` : 'Введите'} 6 цифр из приложения-аутентификатора
          </p>
        </div>

        <form onSubmit={submit} className="card space-y-4">
          <input
            ref={inputRef}
            className="input input-mono text-center text-[26px] tracking-[0.5em]"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="000000"
            required
          />

          {error ? <Alert kind="error">{error}</Alert> : null}

          <button type="submit" className="btn-primary w-full" disabled={busy || code.length < 6}>
            {busy ? 'Проверяем…' : 'Подтвердить'}
          </button>

          <div className="flex items-center justify-between text-[13px]">
            <Link to="/login" className="text-ink2 hover:text-ink">
              ← Назад ко входу
            </Link>
            <span className="text-ink3">Есть резервный код? Введите его</span>
          </div>
        </form>
      </div>
    </div>
  )
}
