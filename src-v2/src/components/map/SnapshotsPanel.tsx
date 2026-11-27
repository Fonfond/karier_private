import { useCallback, useEffect, useMemo, useState } from 'react'
import { Background, Controls, ReactFlow, ReactFlowProvider, type Edge, type Node } from '@xyflow/react'
import { ApiError } from '../../lib/api'
import { gisApi } from '../../lib/gis'
import type { SnapshotBrief, SnapshotDetail, SnapshotPayload, TopologyGraph } from '../../lib/gis'

/**
 * Снимки схемы (Q-6): зафиксировать состояние на дату, посмотреть «как было»,
 * опубликовать согласованную версию.
 *
 * Просмотр — отдельная read-only копия графа: живая схема при этом не меняется
 * и не перезагружается.
 */
export function SnapshotsPanel({
  open,
  onClose,
  canPublish,
}: {
  open: boolean
  onClose: () => void
  canPublish: boolean
}) {
  const [items, setItems] = useState<SnapshotBrief[]>([])
  const [publishedId, setPublishedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [comment, setComment] = useState('')
  const [viewing, setViewing] = useState<SnapshotDetail | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await gisApi.snapshots()
      setItems(data.items)
      setPublishedId(data.published_id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить снимки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) void reload()
  }, [open, reload])

  const create = async () => {
    const trimmed = title.trim()
    if (trimmed.length < 2) {
      setError('Название снимка — минимум 2 символа')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await gisApi.createSnapshot({ title: trimmed, comment: comment.trim() || undefined })
      setTitle('')
      setComment('')
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сделать снимок')
    } finally {
      setSaving(false)
    }
  }

  const publish = async (item: SnapshotBrief) => {
    if (!window.confirm(`Опубликовать версию «${item.title}»? Она станет согласованной схемой на дату.`)) {
      return
    }
    setSaving(true)
    setError(null)
    try {
      await gisApi.publishSnapshot(item.id)
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось опубликовать снимок')
    } finally {
      setSaving(false)
    }
  }

  const view = async (item: SnapshotBrief) => {
    setError(null)
    try {
      setViewing(await gisApi.snapshot(item.id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось открыть снимок')
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[1500] flex items-end justify-center bg-black/60 p-3 sm:items-center">
      <div className="card modal-safe flex max-h-[92vh] w-full max-w-2xl flex-col p-4 text-[13px]">
        <div className="mb-2 flex items-start justify-between gap-3">
          <div>
            <div className="text-[15px] font-semibold">Снимки схемы</div>
            <div className="text-[11px] text-ink3">
              Состояние сети на дату. Публикация фиксирует согласованную версию — живая схема
              продолжает меняться отдельно.
            </div>
          </div>
          <button type="button" className="btn-ghost h-8 px-2" onClick={onClose} title="Закрыть">
            ✕
          </button>
        </div>

        {canPublish ? (
          <div className="mb-3 rounded-lg border border-line p-2">
            <label className="text-[11px] text-ink3">
              Название
              <input
                className="input mt-1 h-8"
                value={title}
                maxLength={160}
                placeholder="Например: План сети на 23.11 после переключений"
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
            <label className="mt-2 block text-[11px] text-ink3">
              Комментарий (необязательно)
              <textarea
                className="input mt-1 min-h-16 w-full"
                value={comment}
                maxLength={2000}
                placeholder="Что изменилось с прошлой версии"
                onChange={(event) => setComment(event.target.value)}
              />
            </label>
            <div className="mt-2 flex justify-end">
              <button type="button" className="btn-primary h-8 px-3" disabled={saving} onClick={create}>
                Сделать снимок
              </button>
            </div>
          </div>
        ) : (
          <p className="mb-3 text-[12px] text-ink3">
            Снимок делает администратор: он фиксирует текущее состояние схемы.
          </p>
        )}

        {error ? <div className="mb-2 rounded border border-danger/40 p-2 text-[12px] text-danger">{error}</div> : null}

        <div className="-mx-1 min-h-24 flex-1 overflow-y-auto px-1">
          {loading ? <div className="p-2 text-[12px] text-ink3">Загрузка…</div> : null}
          {!loading && items.length === 0 ? (
            <div className="p-2 text-[12px] text-ink3">Снимков пока нет.</div>
          ) : null}
          {items.map((item) => (
            <div key={item.id} className="mb-2 rounded-lg border border-line p-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-semibold">{item.title}</span>
                    <span
                      className={
                        item.status === 'published'
                          ? 'rounded bg-ok/20 px-1.5 py-0.5 text-[10px] text-ok'
                          : 'rounded bg-line px-1.5 py-0.5 text-[10px] text-ink3'
                      }
                    >
                      {item.status === 'published' ? 'опубликован' : 'черновик'}
                    </span>
                    {publishedId === item.id ? (
                      <span className="text-[10px] text-ok">текущая версия</span>
                    ) : null}
                  </div>
                  <div className="mt-0.5 text-[11px] text-ink3">
                    {formatDate(item.created_at)} · {item.created_by_name ?? 'автор неизвестен'} ·{' '}
                    {item.counts.nodes} объектов, {item.counts.edges} связей, {item.counts.blocks} блоков
                  </div>
                  {item.comment ? <div className="mt-1 text-[11px] text-ink2">{item.comment}</div> : null}
                  {item.status === 'published' && item.published_at ? (
                    <div className="mt-0.5 text-[11px] text-ok">
                      опубликовал {item.published_by_name ?? '—'} · {formatDate(item.published_at)}
                    </div>
                  ) : null}
                </div>
                <div className="flex shrink-0 gap-1">
                  <button type="button" className="btn-ghost h-8 px-2" onClick={() => void view(item)}>
                    Открыть
                  </button>
                  {canPublish && item.status === 'draft' ? (
                    <button
                      type="button"
                      className="btn-primary h-8 px-2"
                      disabled={saving}
                      onClick={() => void publish(item)}
                    >
                      Опубликовать
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {viewing ? (
        <SnapshotPreview snapshot={viewing} onClose={() => setViewing(null)} />
      ) : null}
    </div>
  )
}

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function previewFromGraph(graph: TopologyGraph): { nodes: Node[]; edges: Edge[] } {
  const positions: Record<string, { x: number; y: number }> = {}
  graph.nodes.forEach((node, index) => {
    positions[node.id] = {
      x: node.schema_x ?? (index % 6) * 240,
      y: node.schema_y ?? Math.floor(index / 6) * 140,
    }
  })

  const nodes: Node[] = graph.nodes.map((node) => ({
    id: node.id,
    position: positions[node.id],
    draggable: false,
    selectable: false,
    data: {
      label: `${node.code}\n${node.name}`,
    },
    style: {
      width: 180,
      padding: '6px 8px',
      fontSize: 11,
      whiteSpace: 'pre-wrap' as const,
      borderRadius: 8,
      background: '#0F172A',
      color: '#E5E7EB',
      border: `1px solid ${node.energized ? '#22C55E' : '#374151'}`,
    },
  }))

  const known = new Set(nodes.map((node) => node.id))
  const edges: Edge[] = graph.edges
    .filter((edge) => known.has(edge.from_asset_id) && known.has(edge.to_asset_id))
    .map((edge) => ({
      id: edge.id,
      source: edge.from_asset_id,
      target: edge.to_asset_id,
      label: edge.label,
      style: { stroke: edge.state === 'connected' ? '#22C55E' : '#6B7280' },
      labelStyle: { fill: '#9CA3AF', fontSize: 10 },
    }))

  return { nodes, edges }
}

function SnapshotPreview({ snapshot, onClose }: { snapshot: SnapshotDetail; onClose: () => void }) {
  const payload: SnapshotPayload = snapshot.payload
  const { nodes, edges } = useMemo(() => previewFromGraph(payload.graph), [payload.graph])

  const download = () => {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `schema-snapshot-${snapshot.id}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="fixed inset-0 z-[1600] flex items-end justify-center bg-black/70 p-3 sm:items-center">
      <div className="card modal-safe flex h-[92vh] w-full max-w-5xl flex-col p-3 text-[13px]">
        <div className="mb-2 flex items-start justify-between gap-2">
          <div>
            <div className="text-[15px] font-semibold">{snapshot.title}</div>
            <div className="text-[11px] text-ink3">
              {formatDate(payload.captured_at)} · {snapshot.created_by_name ?? '—'} ·{' '}
              {payload.counts.nodes} объектов, {payload.counts.edges} связей, {payload.counts.blocks} блоков
              {snapshot.status === 'published' ? ' · опубликован' : ' · черновик'}
            </div>
          </div>
          <div className="flex shrink-0 gap-1">
            <button type="button" className="btn-ghost h-8 px-2" onClick={download} title="Скачать JSON">
              JSON
            </button>
            <button type="button" className="btn-ghost h-8 px-2" onClick={onClose} title="Закрыть">
              ✕
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-line">
          <ReactFlowProvider>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              fitView
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable={false}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={20} color="#1F2937" />
              <Controls showInteractive={false} />
            </ReactFlow>
          </ReactFlowProvider>
        </div>
      </div>
    </div>
  )
}
