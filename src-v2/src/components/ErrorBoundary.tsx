import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
  /** Дополнительный обработчик (например, отправка в мониторинг). */
  onError?: (error: Error, info: ErrorInfo) => void
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * Корневой предохранитель интерфейса: любая необработанная ошибка рендера
 * не должна оставлять пользователя с белым экраном. Показывает сообщение,
 * кнопку «Перезагрузить» и объясняет, что данные не потеряны.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[ErrorBoundary] Необработанная ошибка интерфейса:', error, info.componentStack)
    this.props.onError?.(error, info)
  }

  private handleReload = (): void => {
    window.location.reload()
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children
    return <ErrorScreen error={error} onReload={this.handleReload} />
  }
}

/** Экран ошибки (вынесен отдельно, чтобы можно было проверить разметку без DOM). */
export function ErrorScreen({ error, onReload }: { error: Error; onReload: () => void }) {
  return (
    <div
      role="alert"
      data-testid="error-boundary"
      className="flex min-h-[100dvh] items-center justify-center bg-bg px-4 py-10"
    >
      <div className="w-full max-w-[520px] rounded-2xl border border-bad/40 bg-surface1 p-5">
        <div className="mb-2 text-2xl">⚠️</div>
        <h1 className="text-[19px] font-semibold text-ink">Что-то пошло не так</h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-ink2">
          Интерфейс столкнулся с неожиданной ошибкой. Сохранённые данные и очередь синхронизации не
          потеряны — после перезагрузки приложение продолжит работу.
        </p>
        <p className="mt-3 break-words rounded-lg bg-surface2 px-3 py-2 font-mono text-[11px] text-ink3">
          {error.message || String(error)}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" className="btn-primary px-5" onClick={onReload}>
            Перезагрузить
          </button>
          <button
            type="button"
            className="btn-ghost px-4"
            onClick={() => {
              window.location.assign('/')
            }}
          >
            На главную
          </button>
        </div>
      </div>
    </div>
  )
}
