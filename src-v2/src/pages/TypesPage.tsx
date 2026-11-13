import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Badge, Field, PageTitle } from '../components/ui'
import { ApiError } from '../lib/api'
import type { AssetType } from '../lib/gis'
import { gisApi } from '../lib/gis'

const CATEGORIES = [
  { value: 'source', label: 'Источник питания' },
  { value: 'equipment', label: 'Оборудование' },
  { value: 'mobile', label: 'Мобильный комплекс' },
  { value: 'line', label: 'Линия' },
  { value: 'lighting', label: 'Освещение' },
  { value: 'aux', label: 'Прочее' },
  { value: 'pole', label: 'Опора ВЛ' },
]

const ATTR_OPTIONS: Array<{ key: string; label: string; type: string }> = [
  { key: 'power_kw', label: 'Мощность, кВт', type: 'number' },
  { key: 'power_kva', label: 'Мощность, кВА', type: 'number' },
  { key: 'voltage_in_kv', label: 'Напряжение входа, кВ', type: 'number' },
  { key: 'voltage_out_kv', label: 'Напряжение выхода, кВ', type: 'number' },
  { key: 'drive_type', label: 'Тип привода', type: 'string' },
  { key: 'fuel_type', label: 'Тип топлива', type: 'string' },
  { key: 'bucket_m3', label: 'Ковш, м³', type: 'number' },
]

const TYPE_ICONS = [
  '🏭', '🔌', '⚡', '🔧', '▭', '⏚', '🔁', '🏗', '⛏', '🚜',
  '💡', '🔻', '🪵', '📟', '🧰', '🔋', '🚧', '⛽', '🛠', '📡',
]

const SCHEMA_SYMBOLS = [
  { value: 'breaker', label: 'Выключатель / ячейка' },
  { value: 'disconnector', label: 'Разъединитель' },
  { value: 'busbar', label: 'Секция шин' },
  { value: 'load', label: 'Электроприёмник' },
  { value: 'generator', label: 'Генератор' },
  { value: 'source', label: 'Питание / ПС' },
  { value: 'line', label: 'Опора ВЛ' },
  { value: 'ct', label: 'Трансформатор тока' },
  { value: 'arrester', label: 'ОПН' },
]
interface Draft {
  id: string | null
  code: string
  name: string
  category: string
  schema_symbol: string
  has_maintenance: boolean
  is_composite: boolean
  composite: Record<string, number>
  icon: string
  color: string
  parent_id: string
  description: string
  sort_order: number
  inCount: number
  outCount: number
  voltage: string
  attrs: string[]
  mobile: boolean
}

const EMPTY: Draft = {
  id: null,
  code: '',
  name: '',
  category: 'equipment',
  schema_symbol: 'load',
  has_maintenance: false,
  is_composite: false,
  composite: {},
  icon: '🔧',
  color: '#4C9AFF',
  parent_id: '',
  description: '',
  sort_order: 100,
  inCount: 1,
  outCount: 1,
  voltage: '6',
  attrs: ['power_kw'],
  mobile: false,
}

function draftFrom(type: AssetType): Draft {
  const ports = type.port_template?.ports ?? []
  const firstVoltage = ports.find((port) => port.voltage_kv !== undefined)?.voltage_kv
  return {
    id: type.id,
    code: type.code,
    name: type.name,
    category: type.category,
    schema_symbol: type.schema_symbol ?? 'load',
    has_maintenance: type.has_maintenance ?? false,
    is_composite: type.is_composite ?? false,
    composite: Object.fromEntries((type.composite_template ?? []).map((item) => [String(item.type_code), Number(item.count) || 1])),
    icon: type.icon ?? '🔧',
    color: type.color ?? '#4C9AFF',
    parent_id: type.parent_id ?? '',
    description: type.description ?? '',
    sort_order: type.sort_order,
    inCount: ports.filter((port) => port.kind === 'in').length,
    outCount: ports.filter((port) => port.kind === 'out').length,
    voltage: firstVoltage !== undefined ? String(firstVoltage) : '6',
    attrs: Object.keys(type.attr_schema ?? {}),
    mobile: type.is_mobile_default,
  }
}

function buildPorts(draft: Draft) {
  const voltage = draft.voltage ? Number(draft.voltage.replace(',', '.')) : undefined
  return [
    ...Array.from({ length: draft.inCount }, (_, index) => ({
      code: `IN-${index + 1}`,
      name: draft.inCount === 1 ? 'Ввод' : `Ввод ${index + 1}`,
      kind: 'in',
      voltage_kv: voltage,
    })),
    ...Array.from({ length: draft.outCount }, (_, index) => ({
      code: `OUT-${index + 1}`,
      name: draft.outCount === 1 ? 'Отходящая' : `Отходящая ${index + 1}`,
      kind: 'out',
      voltage_kv: voltage,
    })),
  ]
}

function Editor({
  draft,
  types,
  onClose,
  onSaved,
}: {
  draft: Draft
  types: AssetType[]
  onClose: () => void
  onSaved: (message: string) => void
}) {
  const [form, setForm] = useState<Draft>(draft)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const payload: Record<string, unknown> = {
        name: form.name.trim(),
        category: form.category,
        schema_symbol: form.schema_symbol,
        has_maintenance: form.has_maintenance,
        is_composite: form.is_composite,
        composite_template: Object.entries(form.composite)
          .filter(([, count]) => Number(count) > 0)
          .map(([typeCode, count]) => ({
            type_code: typeCode,
            count: Number(count),
            label: types.find((item) => item.code === typeCode)?.name ?? typeCode,
          })),
        icon: form.icon || '●',
        color: form.color,
        description: form.description.trim() || null,
        sort_order: form.sort_order,
        port_template: { ports: buildPorts(form) },
        attr_schema: Object.fromEntries(
          form.attrs.map((key) => [
            key,
            { type: ATTR_OPTIONS.find((option) => option.key === key)?.type ?? 'string' },
          ]),
        ),
        required_attrs: form.attrs.filter((key) => key === 'power_kw'),
        is_mobile_default: form.mobile,
      }
      if (form.parent_id) payload.parent_id = form.parent_id
      else payload.clear_parent = true

      if (form.id) {
        await gisApi.updateType(form.id, payload)
        onSaved(`Тип «${form.name}» обновлён`)
      } else {
        await gisApi.createType({ ...payload })
        onSaved(`Тип «${form.name}» добавлен`)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить тип')
    } finally {
      setBusy(false)
    }
  }

  const parents = types.filter((type) => type.id !== form.id && type.is_active)

  return (
    <div className="modal-safe fixed inset-0 z-[1400] flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4">
      <div className="max-h-[calc(100dvh-var(--bottom-nav)-16px)] w-full max-w-3xl overflow-y-auto md:max-h-[92vh] rounded-t-2xl border border-line bg-surface1 p-4 sm:rounded-2xl">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[16px] font-semibold">{form.id ? 'Изменить тип' : 'Новый тип'}</h2>
          <button type="button" className="btn-ghost h-9 px-3 text-[12px]" onClick={onClose}>
            Закрыть
          </button>
        </div>

        {error ? <Alert kind="error">{error}</Alert> : null}

        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Код типа">
            <div className="rounded-lg border border-line bg-surface2/40 px-3 py-2 text-[12px] text-ink3">
              {form.id ? form.code : 'создаётся автоматически из названия'}
            </div>
          </Field>
          <div className="sm:col-span-2">
            <Field label="Название">
              <input className="input" value={form.name} onChange={(e) => set('name', e.target.value)} />
            </Field>
          </div>
          <Field label="Категория">
            <select className="input" value={form.category} onChange={(e) => set('category', e.target.value)}>
              {CATEGORIES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Символ на схеме">
            <select
              className="input"
              value={form.schema_symbol}
              onChange={(e) => set('schema_symbol', e.target.value)}
            >
              {SCHEMA_SYMBOLS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Комплектное оборудование">
            <div className="space-y-1 text-[12px] text-ink2">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={form.is_composite}
                  onChange={(e) => set('is_composite', e.target.checked)}
                />
                одно оборудование с ячейками
              </label>
              {form.is_composite ? (
                form.id ? (
                  <div className="space-y-1">
                    {types.filter((item) => item.parent_id === form.id).length === 0 ? (
                      <p className="text-[11px] text-ink3">Сначала добавьте подтипы (ячейки) этого типа.</p>
                    ) : (
                      types
                        .filter((item) => item.parent_id === form.id)
                        .map((child) => (
                          <label key={child.code} className="flex items-center justify-between gap-2">
                            <span className="truncate">{child.name}</span>
                            <input
                              type="number"
                              min={0}
                              className="input h-7 w-16"
                              value={form.composite[child.code] ?? 1}
                              onChange={(e) =>
                                set('composite', { ...form.composite, [child.code]: Number(e.target.value) })
                              }
                            />
                          </label>
                        ))
                    )}
                  </div>
                ) : (
                  <p className="text-[11px] text-ink3">Сохраните тип, затем добавьте подтипы и укажите их количество.</p>
                )
              ) : null}
            </div>
          </Field>
          <Field label="Журнал ТО">
            <label className="flex items-center gap-2 text-[12px] text-ink2">
              <input
                type="checkbox"
                checked={form.has_maintenance}
                onChange={(e) => set('has_maintenance', e.target.checked)}
              />
              вести моточасы, топливо и ТО
            </label>
          </Field>
          <Field label="Иконка">
            <div className="grid max-h-24 grid-cols-8 gap-1 overflow-y-auto rounded-lg border border-line p-1.5">
              {TYPE_ICONS.map((icon) => (
                <button
                  key={icon}
                  type="button"
                  className={`grid h-7 w-7 place-items-center rounded text-[15px] ${
                    form.icon === icon ? 'bg-accent/20 ring-1 ring-accent' : 'hover:bg-surface2'
                  }`}
                  onClick={() => set('icon', icon)}
                >
                  {icon}
                </button>
              ))}
            </div>
            <input
              className="input mt-1.5"
              value={form.icon}
              maxLength={4}
              placeholder="или введите свой"
              onChange={(e) => set('icon', e.target.value)}
            />
          </Field>
          <Field label="Цвет">
            <input
              className="input h-10"
              type="color"
              value={form.color}
              onChange={(e) => set('color', e.target.value)}
            />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Родительский тип (категория)">
              <select
                className="input"
                value={form.parent_id}
                onChange={(e) => set('parent_id', e.target.value)}
              >
                <option value="">— верхний уровень —</option>
                {parents.map((type) => (
                  <option key={type.id} value={type.id}>
                    {type.icon} {type.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Вводов">
            <input
              className="input"
              type="number"
              min={0}
              max={8}
              value={form.inCount}
              onChange={(e) => set('inCount', Number(e.target.value))}
            />
          </Field>
          <Field label="Отходящих">
            <input
              className="input"
              type="number"
              min={0}
              max={12}
              value={form.outCount}
              onChange={(e) => set('outCount', Number(e.target.value))}
            />
          </Field>
          <Field label="Напряжение портов, кВ">
            <input className="input" value={form.voltage} onChange={(e) => set('voltage', e.target.value)} />
          </Field>
          <Field label="Порядок сортировки">
            <input
              className="input"
              type="number"
              value={form.sort_order}
              onChange={(e) => set('sort_order', Number(e.target.value))}
            />
          </Field>
        </div>

        <div className="mt-3">
          <div className="label">Атрибуты</div>
          <div className="flex flex-wrap gap-2">
            {ATTR_OPTIONS.map((attr) => {
              const active = form.attrs.includes(attr.key)
              return (
                <button
                  key={attr.key}
                  type="button"
                  onClick={() =>
                    set('attrs', active ? form.attrs.filter((key) => key !== attr.key) : [...form.attrs, attr.key])
                  }
                  className={`rounded-full border px-3 py-1.5 text-[12px] ${
                    active ? 'border-accent bg-accent/15 text-accent' : 'border-line text-ink2'
                  }`}
                >
                  {attr.label}
                </button>
              )
            })}
          </div>
        </div>

        <label className="mt-3 flex items-center gap-2 text-[13px] text-ink2">
          <input type="checkbox" checked={form.mobile} onChange={(e) => set('mobile', e.target.checked)} />
          Мобильный объект по умолчанию
        </label>

        <div className="mt-3">
          <Field label="Описание">
            <textarea
              className="input min-h-[64px]"
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
            />
          </Field>
        </div>

        <div className="mt-4 flex gap-2">
          <button
            type="button"
            className="btn-primary px-5"
            disabled={busy || form.name.trim().length < 2}
            onClick={() => void save()}
          >
            {busy ? 'Сохраняем…' : form.id ? 'Сохранить' : 'Добавить тип'}
          </button>
          <button type="button" className="btn-ghost" onClick={onClose}>
            Отмена
          </button>
        </div>
      </div>
    </div>
  )
}

export function TypesPage() {
  const [types, setTypes] = useState<AssetType[]>([])
  const [showArchived, setShowArchived] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setTypes(await gisApi.allTypes())
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить справочник')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const tree = useMemo(() => {
    const visible = types.filter((type) => showArchived || type.is_active)
    const childrenOf = new Map<string, AssetType[]>()
    const roots: AssetType[] = []
    visible.forEach((type) => {
      if (type.parent_id) {
        const list = childrenOf.get(type.parent_id) ?? []
        list.push(type)
        childrenOf.set(type.parent_id, list)
      } else {
        roots.push(type)
      }
    })
    return { roots, childrenOf, visible }
  }, [types, showArchived])

  const remove = async (type: AssetType) => {
    if (!window.confirm(`Удалить тип «${type.name}»? Он будет скрыт из справочника.`)) return
    setError(null)
    try {
      await gisApi.deleteType(type.id)
      setNotice(`Тип «${type.name}» перемещён в архив`)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось удалить тип')
    }
  }

  const renderRow = (type: AssetType, depth: number) => {
    const children = tree.childrenOf.get(type.id) ?? []
    return (
      <div key={type.id}>
        <div
          className={`flex flex-wrap items-center gap-2 border-b border-line px-3 py-2 text-[13px] ${
            type.is_active ? '' : 'opacity-50'
          }`}
          style={{ paddingLeft: 12 + depth * 22 }}
        >
          <span className="text-[15px]">{type.icon}</span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="font-medium">{type.name}</span>
              <span className="font-mono text-[11px] text-ink3">{type.code}</span>
              {type.is_mobile_default ? <Badge tone="accent">моб.</Badge> : null}
              {!type.is_active ? <Badge tone="neutral">архив</Badge> : null}
            </div>
            <div className="text-[11px] text-ink3">
              {CATEGORIES.find((item) => item.value === type.category)?.label ?? type.category} · портов{' '}
              {type.port_template?.ports?.length ?? 0} · объектов {type.assets_count}
              {type.parent_name ? ` · в «${type.parent_name}»` : ''}
            </div>
          </div>
          <div className="flex shrink-0 gap-1">
            <button
              type="button"
              className="btn-ghost h-8 px-2 text-[12px]"
              title="Добавить подтип"
              onClick={() => setDraft({ ...EMPTY, parent_id: type.id, category: type.category })}
            >
              ＋ подтип
            </button>
            <button
              type="button"
              className="btn-ghost h-8 px-2 text-[12px]"
              title="Изменить"
              onClick={() => setDraft(draftFrom(type))}
            >
              ✎
            </button>
            {type.is_active ? (
              <button
                type="button"
                className="btn-ghost h-8 px-2 text-[12px] text-warm"
                title="Удалить (в архив)"
                onClick={() => void remove(type)}
              >
                🗑
              </button>
            ) : null}
          </div>
        </div>
        {children.map((child) => renderRow(child, depth + 1))}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageTitle
          title="Справочник типов"
          subtitle="Категории → типы → подтипы. Иконка, цвет, шаблон портов и атрибуты задаются здесь и сразу доступны в реестре"
        />
        <div className="flex gap-2">
          <label className="flex items-center gap-2 text-[12px] text-ink2">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => setShowArchived(e.target.checked)}
            />
            архивные
          </label>
          <button type="button" className="btn-primary admin-only h-10 px-4 text-[13px]" onClick={() => setDraft({ ...EMPTY })}>
            + Тип
          </button>
        </div>
      </div>

      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      <div className="card overflow-hidden p-0">
        {tree.roots.length === 0 ? (
          <p className="p-4 text-[13px] text-ink3">Справочник пуст — добавьте первый тип.</p>
        ) : (
          tree.roots.map((type) => renderRow(type, 0))
        )}
      </div>

      {draft ? (
        <Editor
          draft={draft}
          types={tree.visible}
          onClose={() => setDraft(null)}
          onSaved={async (message) => {
            setDraft(null)
            setNotice(message)
            await load()
          }}
        />
      ) : null}
    </div>
  )
}
