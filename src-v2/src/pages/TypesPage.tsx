import { useCallback, useEffect, useState } from 'react'
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

interface PortDraft {
  inCount: number
  outCount: number
  voltage: string
}

export function TypesPage() {
  const [types, setTypes] = useState<AssetType[]>([])
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [category, setCategory] = useState('equipment')
  const [icon, setIcon] = useState('🔧')
  const [color, setColor] = useState('#4C9AFF')
  const [ports, setPorts] = useState<PortDraft>({ inCount: 1, outCount: 1, voltage: '6' })
  const [attrs, setAttrs] = useState<string[]>(['power_kw'])
  const [mobile, setMobile] = useState(false)

  const load = useCallback(async () => {
    try {
      setTypes(await gisApi.types())
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить справочник')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const create = async () => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const voltage = ports.voltage ? Number(ports.voltage.replace(',', '.')) : undefined
      const portList = [
        ...Array.from({ length: ports.inCount }, (_, index) => ({
          code: `IN-${index + 1}`,
          name: ports.inCount === 1 ? 'Ввод' : `Ввод ${index + 1}`,
          kind: 'in',
          voltage_kv: voltage,
        })),
        ...Array.from({ length: ports.outCount }, (_, index) => ({
          code: `OUT-${index + 1}`,
          name: ports.outCount === 1 ? 'Отходящая' : `Отходящая ${index + 1}`,
          kind: 'out',
          voltage_kv: voltage,
        })),
      ]

      await gisApi.createType({
        code: code.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_'),
        name: name.trim(),
        category,
        icon,
        color,
        port_template: { ports: portList },
        attr_schema: Object.fromEntries(
          attrs.map((key) => [
            key,
            { type: ATTR_OPTIONS.find((option) => option.key === key)?.type ?? 'string' },
          ]),
        ),
        required_attrs: attrs.filter((key) => key === 'power_kw'),
        is_mobile_default: mobile,
        sort_order: 100,
      })
      setNotice(`Тип «${name}» добавлен — он сразу доступен при создании объектов`)
      setCode('')
      setName('')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать тип')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <PageTitle
        title="Справочник типов"
        subtitle="Номенклатура оборудования: иконка, цвет, шаблон портов и набор атрибутов. Названия берутся только из БД"
      />

      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      <div className="card">
        <h2 className="mb-3 text-[15px] font-semibold">Новый тип</h2>
        <div className="grid gap-3 md:grid-cols-4">
          <Field label="Код (латиницей)">
            <input className="input" value={code} onChange={(e) => setCode(e.target.value)} placeholder="dmo2" />
          </Field>
          <div className="md:col-span-2">
            <Field label="Название">
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="ДМО — Дробильный мобильный комплекс"
              />
            </Field>
          </div>
          <Field label="Категория">
            <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Иконка (эмодзи)">
            <input className="input" value={icon} onChange={(e) => setIcon(e.target.value)} maxLength={4} />
          </Field>
          <Field label="Цвет">
            <input
              className="input h-10"
              type="color"
              value={color}
              onChange={(e) => setColor(e.target.value)}
            />
          </Field>
          <Field label="Вводов">
            <input
              className="input"
              type="number"
              min={0}
              max={8}
              value={ports.inCount}
              onChange={(e) => setPorts({ ...ports, inCount: Number(e.target.value) })}
            />
          </Field>
          <Field label="Отходящих">
            <input
              className="input"
              type="number"
              min={0}
              max={12}
              value={ports.outCount}
              onChange={(e) => setPorts({ ...ports, outCount: Number(e.target.value) })}
            />
          </Field>
          <Field label="Напряжение портов, кВ">
            <input
              className="input"
              value={ports.voltage}
              onChange={(e) => setPorts({ ...ports, voltage: e.target.value })}
              placeholder="6"
            />
          </Field>
        </div>

        <div className="mt-3">
          <div className="label">Атрибуты</div>
          <div className="flex flex-wrap gap-2">
            {ATTR_OPTIONS.map((attr) => {
              const active = attrs.includes(attr.key)
              return (
                <button
                  key={attr.key}
                  type="button"
                  onClick={() =>
                    setAttrs((prev) => (active ? prev.filter((key) => key !== attr.key) : [...prev, attr.key]))
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
          <input type="checkbox" checked={mobile} onChange={(e) => setMobile(e.target.checked)} />
          Мобильный объект по умолчанию (можно перемещать)
        </label>

        <div className="mt-4 flex gap-2">
          <button
            type="button"
            className="btn-primary px-5"
            disabled={busy || code.trim().length < 2 || name.trim().length < 2}
            onClick={() => void create()}
          >
            {busy ? 'Сохраняем…' : 'Добавить тип'}
          </button>
        </div>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full min-w-[720px] text-left text-[13px]">
          <thead className="bg-surface2/60 text-[12px] uppercase tracking-wide text-ink3">
            <tr>
              <th className="px-3 py-2 font-medium">Тип</th>
              <th className="px-3 py-2 font-medium">Код</th>
              <th className="px-3 py-2 font-medium">Категория</th>
              <th className="px-3 py-2 font-medium">Порты</th>
              <th className="px-3 py-2 font-medium">Атрибуты</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {types.map((type) => (
              <tr key={type.id}>
                <td className="px-3 py-2">
                  <span className="mr-2">{type.icon}</span>
                  {type.name}
                  {type.is_mobile_default ? <span className="ml-2"><Badge tone="accent">моб.</Badge></span> : null}
                </td>
                <td className="px-3 py-2 font-mono text-[12px] text-ink2">{type.code}</td>
                <td className="px-3 py-2 text-ink2">{type.category}</td>
                <td className="px-3 py-2 text-ink2">{type.port_template?.ports?.length ?? 0}</td>
                <td className="px-3 py-2 text-ink3">
                  {Object.keys(type.attr_schema ?? {}).join(', ') || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
