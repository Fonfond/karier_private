import { useEffect, useState } from 'react'
import { ApiError } from '../../lib/api'
import { gisApi } from '../../lib/gis'

/**
 * Пакетное добавление ячеек в блок/контур: сквозная нумерация и секции.
 * Каждая ячейка создаётся как объект реестра с parent_id и attrs.section.
 */
export function BulkCellsDialog({
  parentId,
  parentName,
  open,
  onClose,
  onCreated,
}: {
  parentId: string | null
  parentName: string
  open: boolean
  onClose: () => void
  onCreated: (cells: Array<{ id: string; name: string }>, parentId: string) => void
}) {
  const [count, setCount] = useState('10')
  const [start, setStart] = useState('1')
  const [prefix, setPrefix] = useState('Яч. №')
  const [suffix, setSuffix] = useState('')
  const [sectionSize, setSectionSize] = useState('0')
  const [sectionPrefix, setSectionPrefix] = useState('Секция')
  const [role, setRole] = useState<'outgoing' | 'incoming' | 'cell'>('outgoing')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setError(null)
      setSaving(false)
    }
  }, [open])

  if (!open || !parentId) return null

  const total = Math.max(1, Math.min(200, Number(count) || 1))
  const perSection = Math.max(0, Math.min(200, Number(sectionSize) || 0))
  const sections = perSection > 0 ? Math.ceil(total / perSection) : 0
  const preview = Array.from({ length: Math.min(total, 4) }, (_, index) => `${prefix}${(Number(start) || 1) + index}${suffix}`)

  const submit = async () => {
    setSaving(true)
    setError(null)
    try {
      const result = await gisApi.addBlockCellsBulk(parentId, {
        count: total,
        start: Number(start) || 1,
        prefix: prefix || 'Яч. №',
        suffix,
        section_size: perSection,
        section_prefix: sectionPrefix || 'Секция',
        role,
      })
      onCreated(result.items.map((item) => ({ id: item.id, name: item.name })), parentId)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось добавить ячейки')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[1550] flex items-end justify-center bg-black/60 p-3 sm:items-center">
      <div className="card modal-safe w-full max-w-md p-4 text-[13px]">
        <div className="mb-2 flex items-start justify-between gap-2">
          <div>
            <div className="text-[15px] font-semibold">Ячейки пачкой</div>
            <div className="text-[11px] text-ink3">{parentName} · сквозная нумерация и секции</div>
          </div>
          <button type="button" className="btn-ghost h-8 px-2" onClick={onClose} title="Закрыть">
            ✕
          </button>
        </div>

        {error ? <div className="mb-2 rounded border border-danger/40 p-2 text-[12px] text-danger">{error}</div> : null}

        <div className="grid grid-cols-2 gap-2">
          <label className="text-[11px] text-ink3">
            Сколько ячеек
            <input className="input mt-1 h-8" inputMode="numeric" value={count} onChange={(event) => setCount(event.target.value)} />
          </label>
          <label className="text-[11px] text-ink3">
            Стартовый номер
            <input className="input mt-1 h-8" inputMode="numeric" value={start} onChange={(event) => setStart(event.target.value)} />
          </label>
          <label className="text-[11px] text-ink3">
            Префикс имени
            <input className="input mt-1 h-8" value={prefix} onChange={(event) => setPrefix(event.target.value)} />
          </label>
          <label className="text-[11px] text-ink3">
            Суффикс
            <input className="input mt-1 h-8" value={suffix} onChange={(event) => setSuffix(event.target.value)} />
          </label>
          <label className="text-[11px] text-ink3">
            Ячеек в секции
            <input className="input mt-1 h-8" inputMode="numeric" value={sectionSize} onChange={(event) => setSectionSize(event.target.value)} />
          </label>
          <label className="text-[11px] text-ink3">
            Префикс секции
            <input className="input mt-1 h-8" value={sectionPrefix} onChange={(event) => setSectionPrefix(event.target.value)} />
          </label>
        </div>

        <label className="mt-2 block text-[11px] text-ink3">
          Роль ячейки
          <select className="input mt-1 h-8" value={role} onChange={(event) => setRole(event.target.value as 'outgoing' | 'incoming' | 'cell')}>
            <option value="outgoing">отходящая</option>
            <option value="incoming">вводная</option>
            <option value="cell">ячейка</option>
          </select>
        </label>

        <p className="mt-2 text-[11px] text-ink3">
          {preview.join(', ')}
          {total > preview.length ? ` … ${prefix}${(Number(start) || 1) + total - 1}${suffix}` : ''}
          {sections > 0 ? ` · ${sections} секц. по ${perSection}` : ' · без секций'}
        </p>

        <div className="mt-3 flex justify-end gap-2">
          <button type="button" className="btn-ghost h-8 px-3" onClick={onClose}>
            Отмена
          </button>
          <button type="button" className="btn-primary h-8 px-3" disabled={saving} onClick={submit}>
            {saving ? 'Добавляем…' : `Добавить ${total}`}
          </button>
        </div>
      </div>
    </div>
  )
}
