import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Badge } from '../ui'
import { ApiError } from '../../lib/api'
import type { DocumentOut } from '../../lib/gis'
import { DOC_TYPE_LABEL, gisApi } from '../../lib/gis'
import {
  formatSize,
  getDocOffline,
  listOfflineDocs,
  removeOfflineDoc,
  saveDocOffline,
} from '../../lib/offlineDocs'

interface Props {
  assetId: string
  canManage: boolean
}

const ICONS: Array<[string, string]> = [
  ['application/pdf', '📄'],
  ['image/', '🖼'],
  ['sheet', '📊'],
  ['word', '📝'],
  ['zip', '🗜'],
]

function iconFor(mime: string): string {
  for (const [needle, icon] of ICONS) {
    if (mime.includes(needle)) return icon
  }
  return '📎'
}

export function DocumentsTab({ assetId, canManage }: Props) {
  const [items, setItems] = useState<DocumentOut[]>([])
  const [offlineIds, setOfflineIds] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [viewer, setViewer] = useState<{ url: string; title: string; offline: boolean } | null>(null)
  const [docType, setDocType] = useState('schematic')
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const refreshOffline = useCallback(async () => {
    const cached = await listOfflineDocs()
    setOfflineIds(new Set(cached.map((item) => item.id)))
  }, [])

  const load = useCallback(async () => {
    try {
      const data = await gisApi.documents(assetId)
      setItems(data.items)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить документы')
    }
    await refreshOffline()
  }, [assetId, refreshOffline])

  useEffect(() => {
    void load()
  }, [load])

  const upload = async () => {
    const file = fileRef.current?.files?.[0]
    if (!file) {
      setError('Выберите файл')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await gisApi.uploadDocument(assetId, file, docType, title || file.name)
      if (fileRef.current) fileRef.current.value = ''
      setTitle('')
      setNotice('Документ загружен')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить документ')
    } finally {
      setBusy(false)
    }
  }

  const saveOffline = async (doc: DocumentOut) => {
    try {
      await saveDocOffline({
        id: doc.id,
        assetId,
        title: doc.title,
        fileName: doc.file_name,
        mime: doc.mime,
        contentUrl: doc.content_url,
      })
      await refreshOffline()
      setNotice(`«${doc.title}» сохранён офлайн`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить офлайн')
    }
  }

  const openOffline = async (doc: DocumentOut) => {
    const cached = await getDocOffline(doc.id)
    if (!cached) {
      setError('Файл не найден в офлайн-кэше')
      return
    }
    const url = URL.createObjectURL(cached.blob)
    setViewer({ url, title: doc.title, offline: true })
  }

  const openOnline = (doc: DocumentOut) => {
    setViewer({ url: doc.content_url, title: doc.title, offline: false })
  }

  return (
    <div className="space-y-3">
      {items.length === 0 ? (
        <p className="hint">Документов пока нет. Администратор может загрузить электросхему, уставки или инструкцию.</p>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((doc) => {
            const cached = offlineIds.has(doc.id)
            return (
              <li key={doc.id} className="flex items-start gap-3 py-3">
                <span className="text-xl">{iconFor(doc.mime)}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[14px] font-medium">{doc.title}</span>
                    <Badge tone={doc.doc_type === 'schematic' ? 'accent' : 'neutral'}>
                      {DOC_TYPE_LABEL[doc.doc_type] ?? doc.doc_type}
                    </Badge>
                    {cached ? <Badge tone="ok">офлайн</Badge> : null}
                  </div>
                  <div className="mt-0.5 text-[12px] text-ink3">
                    {doc.file_name} · {formatSize(doc.size_bytes)} ·{' '}
                    {new Date(doc.created_at).toLocaleDateString('ru-RU')}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      className="btn-ghost h-8 px-2.5 text-[12px]"
                      onClick={() => openOnline(doc)}
                    >
                      Открыть
                    </button>
                    {cached ? (
                      <button
                        type="button"
                        className="btn-ghost h-8 px-2.5 text-[12px] text-ok"
                        onClick={() => void openOffline(doc)}
                      >
                        Офлайн-версия
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="btn-ghost h-8 px-2.5 text-[12px]"
                        onClick={() => void saveOffline(doc)}
                      >
                        Скачать офлайн
                      </button>
                    )}
                    {cached && canManage ? (
                      <button
                        type="button"
                        className="btn-ghost h-8 px-2.5 text-[12px] text-ink3"
                        onClick={async () => {
                          await removeOfflineDoc(doc.id)
                          await refreshOffline()
                        }}
                      >
                        Из кэша
                      </button>
                    ) : null}
                    {canManage ? (
                      <button
                        type="button"
                        className="btn-ghost h-8 px-2.5 text-[12px] text-bad"
                        onClick={async () => {
                          await gisApi.deleteDocument(doc.id)
                          await removeOfflineDoc(doc.id)
                          await load()
                        }}
                      >
                        Удалить
                      </button>
                    ) : null}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {canManage ? (
        <div className="rounded-xl border border-line bg-surface2/50 p-3">
          <div className="mb-2 text-[12px] uppercase tracking-wide text-ink3">Загрузить документ</div>
          <div className="space-y-2">
            <input
              ref={fileRef}
              type="file"
              className="block w-full text-[12px] text-ink2 file:mr-3 file:rounded-lg file:border-0 file:bg-surface2 file:px-3 file:py-2 file:text-[12px] file:text-ink"
            />
            <div className="flex flex-wrap gap-2">
              <select
                className="input h-9 w-auto text-[12px]"
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
              >
                {Object.entries(DOC_TYPE_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <input
                className="input h-9 flex-1 text-[12px]"
                placeholder="Название (необязательно)"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
              <button
                type="button"
                className="btn-primary h-9 px-3 text-[12px]"
                disabled={busy}
                onClick={() => void upload()}
              >
                {busy ? 'Загружаем…' : 'Загрузить'}
              </button>
            </div>
            <p className="text-[11px] text-ink3">PDF, изображения, Word, Excel, ZIP — до 25 МБ</p>
          </div>
        </div>
      ) : null}

      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      {viewer ? (
        <div className="fixed inset-0 z-[1400] flex flex-col bg-black/80 p-3 backdrop-blur">
          <div className="mb-2 flex items-center justify-between gap-3 rounded-xl bg-surface1 px-3 py-2">
            <div className="min-w-0">
              <div className="truncate text-[14px] font-medium">{viewer.title}</div>
              {viewer.offline ? (
                <div className="text-[11px] text-warm">Офлайн-версия · из кэша устройства</div>
              ) : (
                <div className="text-[11px] text-ink3">Открыто с сервера</div>
              )}
            </div>
            <button
              type="button"
              className="btn-ghost h-9 px-3 text-[12px]"
              onClick={() => {
                if (viewer.offline) URL.revokeObjectURL(viewer.url)
                setViewer(null)
              }}
            >
              Закрыть
            </button>
          </div>
          <div className="flex-1 overflow-hidden rounded-xl bg-surface2">
            {viewer.url.toLowerCase().includes('.pdf') || viewer.url.includes('application/pdf') ? (
              <iframe src={viewer.url} title={viewer.title} className="h-full w-full" />
            ) : (
              <iframe src={viewer.url} title={viewer.title} className="h-full w-full bg-white" />
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}
