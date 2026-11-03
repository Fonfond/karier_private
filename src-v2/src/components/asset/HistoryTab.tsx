import { useCallback, useEffect, useState } from 'react'
import { Alert } from '../ui'
import { ApiError } from '../../lib/api'
import type { HistoryEntry } from '../../lib/opsApi'
import { opsApi } from '../../lib/opsApi'

const KIND_ICON: Record<string, string> = {
  inspection: '📋',
  defect: '⚠️',
  media: '📷',
  switching: '🔀',
}

const STATUS_LABEL: Record<string, string> = {
  ok: 'норма',
  defect: 'дефект',
  critical: 'критично',
  no_access: 'нет доступа',
  not_found: 'не найден',
  open: 'открыт',
  in_progress: 'в работе',
  fixed: 'устранён',
  accepted: 'принят',
  rejected: 'отклонён',
  submitted: 'отправлен',
  grounded: 'заземлено',
}

export function HistoryTab({ assetId }: { assetId: string }) {
  const [items, setItems] = useState<HistoryEntry[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await opsApi.history(assetId)
      setItems(data.items)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить историю')
    }
  }, [assetId])

  useEffect(() => {
    void load()
  }, [load])

  if (error) return <Alert kind="error">{error}</Alert>
  if (items.length === 0) return <p className="hint">Событий пока нет: обходы, дефекты и фото появятся здесь.</p>

  return (
    <ul className="space-y-2">
      {items.map((entry, index) => (
        <li key={`${entry.kind}-${index}`} className="flex gap-3 rounded-lg border border-line bg-surface1 p-2.5">
          <span className="text-base">{KIND_ICON[entry.kind] ?? '•'}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-2">
              <span className="text-[13px] font-medium">{entry.title}</span>
              {entry.status ? (
                <span className="rounded-full bg-surface2 px-2 py-0.5 text-[10px] text-ink2">
                  {STATUS_LABEL[entry.status] ?? entry.status}
                </span>
              ) : null}
            </div>
            {entry.detail ? <div className="text-[12px] text-ink2">{entry.detail}</div> : null}
            <div className="text-[11px] text-ink3">
              {new Date(entry.at).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })}
              {entry.author ? ` · ${entry.author}` : ''}
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}
