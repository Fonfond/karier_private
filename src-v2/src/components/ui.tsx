import type { ReactNode } from 'react'

export function Splash() {
  return (
    <div className="flex h-full min-h-screen items-center justify-center bg-bg">
      <div className="flex flex-col items-center gap-4">
        <div className="h-10 w-10 animate-spin rounded-full border-2 border-line border-t-accent" />
        <p className="text-sm text-ink2">Проверяем сессию…</p>
      </div>
    </div>
  )
}

export function Alert({ kind, children }: { kind: 'error' | 'success' | 'info'; children: ReactNode }) {
  const cls =
    kind === 'error' ? 'error-box' : kind === 'success' ? 'success-box' : 'hint rounded-xl border border-line bg-surface2 px-4 py-3'
  return (
    <div className={cls} role={kind === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  )
}

export function Badge({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'ok' | 'bad' | 'warm' | 'accent'
  children: ReactNode
}) {
  const tones: Record<string, string> = {
    neutral: 'border-line text-ink2',
    ok: 'border-ok/40 bg-ok/10 text-ok',
    bad: 'border-bad/40 bg-bad/10 text-bad',
    warm: 'border-warm/40 bg-warm/10 text-warm',
    accent: 'border-accent/40 bg-accent/10 text-accent',
  }
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[12px] ${tones[tone]}`}>
      {children}
    </span>
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-[12px] text-ink3">{hint}</span> : null}
    </label>
  )
}

export function PageTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-[22px] font-semibold leading-tight">{title}</h1>
      {subtitle ? <p className="mt-1 text-[13px] text-ink2">{subtitle}</p> : null}
    </div>
  )
}
