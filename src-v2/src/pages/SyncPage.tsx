import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { Alert, Badge, PageTitle } from '../components/ui'
import { listOps } from '../lib/outbox'
import type { OutboxOp } from '../lib/outbox'
import type { ConflictItem } from '../lib/syncApi'
import { syncApi } from '../lib/syncApi'
import { useOutbox } from '../lib/useOutbox'
import { ApiError } from '../lib/api'

const KIND_LABEL: Record<string, string> = {
  inspection_create: 'Создание обхода',
  inspection_item: 'Отметка объекта',
  inspection_submit: 'Завершение обхода',
  defect: 'Дефект',
  media: 'Фото',
  asset_move: 'Перемещение',
  asset_update: 'Изменение статуса',
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

export function SyncPage() {
  const { user } = useAuth()
  const { pending, online, syncing, sync } = useOutbox()
  const [ops, setOps] = useState<OutboxOp[]>([])
  const [conflicts, setConflicts] = useState<ConflictItem[]>([])
  const [state, setState] = useState<{ last_seq: number; conflicts: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    setOps(await listOps())
    try {
      const [conflictData, stateData] = await Promise.all([syncApi.conflicts(), syncApi.state()])
      setConflicts(conflictData.items)
      setState(stateData)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось получить состояние синхронизации')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, pending])

  const runSync = async () => {
    const result = await sync()
    setNotice(
      result.sent || result.failed || result.conflicts
        ? `Отправлено: ${result.sent}, конфликтов: ${result.conflicts}, ошибок: ${result.failed}`
        : 'Очередь пуста',
    )
    await load()
  }

  return (
    <div className="space-y-4">
      <PageTitle
        title="Синхронизация"
        subtitle={`Устройство: ${user?.tab_no ?? '—'} · ${online ? 'сеть есть' : 'нет сети'}`}
      />

      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      <div className="grid gap-3 sm:grid-cols-3">
        <div className="card">
          <div className="text-[11px] uppercase tracking-wide text-ink3">В очереди</div>
          <div className="mt-1 text-[26px] font-semibold">{pending}</div>
          <div className="text-[12px] text-ink3">операций ждут отправки</div>
        </div>
        <div className="card">
          <div className="text-[11px] uppercase tracking-wide text-ink3">Конфликты</div>
          <div className="mt-1 text-[26px] font-semibold">{state?.conflicts ?? conflicts.length}</div>
          <div className="text-[12px] text-ink3">зафиксировано сервером</div>
        </div>
        <div className="card">
          <div className="text-[11px] uppercase tracking-wide text-ink3">Курсор изменений</div>
          <div className="mt-1 text-[26px] font-semibold">{state?.last_seq ?? '—'}</div>
          <div className="text-[12px] text-ink3">seq журнала change_log</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn-primary px-5" disabled={syncing} onClick={() => void runSync()}>
          {syncing ? 'Синхронизируем…' : 'Синхронизировать сейчас'}
        </button>
        <button type="button" className="btn-ghost px-4" onClick={() => void load()}>
          Обновить
        </button>
        <span className="self-center text-[12px] text-ink3">
          {online ? 'Очередь уходит автоматически при появлении сети' : 'Ждём сеть — данные не потеряются'}
        </span>
      </div>

      <div className="card">
        <h2 className="mb-3 text-[15px] font-semibold">Очередь на устройстве</h2>
        {ops.length === 0 ? (
          <p className="hint">Очередь пуста — все изменения доставлены.</p>
        ) : (
          <ul className="divide-y divide-line">
            {ops.map((op) => (
              <li key={op.id} className="flex items-start gap-3 py-2.5 text-[13px]">
                <span className="text-base">{op.kind === 'media' || op.kind === 'defect' ? '📷' : op.kind === 'asset_move' ? '🚚' : '📋'}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span>{KIND_LABEL[op.kind] ?? op.kind}</span>
                    <Badge tone={op.attempts > 0 ? 'warm' : 'neutral'}>
                      {op.attempts > 0 ? `попыток: ${op.attempts}` : 'ждёт отправки'}
                    </Badge>
                  </div>
                  <div className="text-[11px] text-ink3">
                    {formatDate(op.createdAt)}
                    {op.lastError ? ` · ${op.lastError}` : ''}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card">
        <h2 className="mb-3 text-[15px] font-semibold">Конфликты версий</h2>
        {conflicts.length === 0 ? (
          <p className="hint">Конфликтов нет: данные на устройстве и на сервере совпадали.</p>
        ) : (
          <ul className="space-y-2">
            {conflicts.map((conflict) => (
              <li key={conflict.id} className="rounded-xl border border-warm/40 bg-warm/5 p-3 text-[13px]">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[12px]">{conflict.entity}</span>
                  <Badge tone={conflict.winner === 'client' ? 'ok' : 'warm'}>
                    {conflict.winner === 'client' ? 'применено ваше' : 'оставлено серверное'}
                  </Badge>
                  <span className="text-[11px] text-ink3">{formatDate(conflict.created_at)}</span>
                </div>
                <div className="mt-1 text-ink2">{conflict.note}</div>
                <div className="mt-1 text-[11px] text-ink3">
                  Ваше: {JSON.stringify(conflict.loser_payload ?? {}).slice(0, 160)}
                </div>
                {conflict.actor_name ? (
                  <div className="text-[11px] text-ink3">Автор изменения: {conflict.actor_name}</div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="card text-[12px] text-ink3">
        <p className="mb-1">
          <b className="text-ink2">Как разрешаются конфликты.</b> Для статусов и заземления побеждает
          более позднее изменение по времени устройства (LWW). Проигравшее изменение не теряется: оно
          записывается в журнал конфликтов и аудит.
        </p>
        <p>
          Перемещения «кукушек» сохраняются оба: текущее положение — по более позднему времени, второе
          остаётся в истории объекта.
        </p>
      </div>
    </div>
  )
}
