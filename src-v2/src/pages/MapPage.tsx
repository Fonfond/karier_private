import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { BottomSheet } from '../components/BottomSheet'
import { MapView } from '../components/map/MapView'
import { Alert } from '../components/ui'
import { ApiError } from '../lib/api'
import type { AssetBrief, AssetOut, AssetType, MapLayer, PowerPath } from '../lib/gis'
import { STATUS_COLOR, STATUS_LABEL, gisApi } from '../lib/gis'

const CATEGORIES: Array<{ key: string | null; label: string }> = [
  { key: null, label: 'Все' },
  { key: 'source', label: 'Источники' },
  { key: 'equipment', label: 'Оборудование' },
  { key: 'mobile', label: 'Мобильные' },
  { key: 'lighting', label: 'Освещение' },
  { key: 'aux', label: 'Прочее' },
]

const ATTR_LABELS: Record<string, string> = {
  power_kw: 'Мощность, кВт',
  power_kva: 'Мощность, кВА',
  voltage_in_kv: 'Напряжение входа, кВ',
  voltage_out_kv: 'Напряжение выхода, кВ',
  fuel_type: 'Топливо',
  drive_type: 'Привод',
  bucket_m3: 'Ковш, м³',
  section_breaker: 'Секционный выключатель',
}

export function MapPage() {
  const { can } = useAuth()
  const [layer, setLayer] = useState<MapLayer | null>(null)
  const [assets, setAssets] = useState<AssetBrief[]>([])
  const [types, setTypes] = useState<AssetType[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const [category, setCategory] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selected, setSelected] = useState<AssetOut | null>(null)
  const [path, setPath] = useState<PowerPath | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState<{ x: number; y: number } | null>(null)
  const [formType, setFormType] = useState('ktp')
  const [formName, setFormName] = useState('')
  const [formCode, setFormCode] = useState('')
  const [formPower, setFormPower] = useState('')
  const [formLocation, setFormLocation] = useState('')
  const [saving, setSaving] = useState(false)

  const isAdmin = can('asset.create')

  const load = useCallback(async () => {
    try {
      const [layerData, assetsData, typesData] = await Promise.all([
        gisApi.layer(),
        gisApi.assets(),
        gisApi.types(),
      ])
      setLayer(layerData)
      setAssets(assetsData.items)
      setTypes(typesData)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить карту')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const openAsset = useCallback(async (id: string) => {
    setSelectedId(id)
    setSheetOpen(true)
    setConfirmDelete(false)
    try {
      const [detail, powerPath] = await Promise.all([gisApi.asset(id), gisApi.powerPath(id)])
      setSelected(detail)
      setPath(powerPath)
    } catch {
      setSelected(null)
      setPath(null)
    }
  }, [])

  const filtered = useMemo(() => {
    if (!category) return assets
    return assets.filter((asset) => asset.type.category === category)
  }, [assets, category])

  const startAdding = () => {
    setAdding(true)
    setDraft(null)
    setSheetOpen(false)
    setSelected(null)
    setError(null)
  }

  const cancelAdding = () => {
    setAdding(false)
    setDraft(null)
  }

  const handleMapClick = (x: number, y: number) => {
    setDraft({ x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 })
    setSheetOpen(true)
    setSelected(null)
    setPath(null)
    setFormName('')
    setFormCode('')
    setFormPower('')
    setFormLocation('')
    setFormType(types.find((type) => type.sort_order > 0)?.code ?? 'ktp')
  }

  const submitCreate = async () => {
    if (!draft) return
    setSaving(true)
    setError(null)
    try {
      const attrs: Record<string, unknown> = {}
      if (formPower.trim()) attrs.power_kw = Number(formPower.replace(',', '.'))
      const created = await gisApi.create({
        name: formName.trim(),
        type_code: formType,
        code: formCode.trim() || undefined,
        x: draft.x,
        y: draft.y,
        location_text: formLocation.trim() || undefined,
        attrs,
      })
      setAdding(false)
      setDraft(null)
      await load()
      await openAsset(created.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать объект')
    } finally {
      setSaving(false)
    }
  }

  const removeSelected = async () => {
    if (!selected) return
    if (!confirmDelete) {
      setConfirmDelete(true)
      return
    }
    try {
      await gisApi.remove(selected.id)
      setSheetOpen(false)
      setSelected(null)
      setSelectedId(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось удалить объект')
    }
  }

  const activeType = types.find((type) => type.code === formType)

  return (
    <div className="absolute inset-0 overflow-hidden bg-[#070C10]">
      {layer ? (
        <MapView
          layer={layer}
          assets={filtered}
          selectedId={selectedId}
          onSelect={openAsset}
          adding={adding}
          onMapClick={handleMapClick}
          draft={draft}
        />
      ) : (
        <div className="flex h-full items-center justify-center text-ink2">
          {loading ? 'Загружаем карту…' : 'Карта недоступна'}
        </div>
      )}

      {/* фильтры */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-[1000] p-3">
        <div className="pointer-events-auto flex flex-wrap items-center gap-2">
          <div className="flex max-w-full gap-1 overflow-x-auto rounded-full border border-line bg-bg/85 p-1 backdrop-blur">
            {CATEGORIES.map((item) => (
              <button
                key={item.label}
                type="button"
                onClick={() => setCategory(item.key)}
                className={`whitespace-nowrap rounded-full px-3 py-1.5 text-[12px] transition ${
                  category === item.key ? 'bg-accent text-[#08131F]' : 'text-ink2 hover:text-ink'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <span className="rounded-full border border-line bg-bg/85 px-3 py-1.5 text-[12px] text-ink2 backdrop-blur">
            {filtered.length} из {assets.length}
          </span>
        </div>

        {adding ? (
          <div className="pointer-events-auto mt-2 flex items-center justify-between gap-3 rounded-xl border border-accent/40 bg-accent/10 px-3 py-2 text-[13px] text-accent backdrop-blur">
            <span>
              {draft
                ? `Точка: X ${draft.x} м, Y ${draft.y} м — заполните карточку`
                : 'Кликните по карте, чтобы поставить объект'}
            </span>
            <button type="button" className="text-[12px] underline" onClick={cancelAdding}>
              Отмена
            </button>
          </div>
        ) : null}

        {error ? (
          <div className="pointer-events-auto mt-2 max-w-[520px]">
            <Alert kind="error">{error}</Alert>
          </div>
        ) : null}
      </div>

      {/* легенда */}
      <div className="pointer-events-none absolute bottom-4 left-3 z-[1000] hidden rounded-xl border border-line bg-bg/85 p-3 text-[11px] backdrop-blur sm:block">
        <div className="mb-1.5 text-ink3">Состояние</div>
        {['on', 'off', 'standby', 'maintenance'].map((status) => (
          <div key={status} className="flex items-center gap-2 py-0.5 text-ink2">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: STATUS_COLOR[status] }}
            />
            {STATUS_LABEL[status]}
          </div>
        ))}
      </div>

      {/* добавление */}
      {isAdmin && !adding ? (
        <button
          type="button"
          onClick={startAdding}
          className="absolute bottom-5 right-4 z-[1000] flex h-14 items-center gap-2 rounded-full bg-accent px-5 text-[14px] font-semibold text-[#08131F] shadow-lg active:scale-[0.98]"
        >
          <span className="text-xl leading-none">＋</span> Объект
        </button>
      ) : null}

      {/* карточка объекта */}
      <BottomSheet
        open={sheetOpen && !draft}
        onClose={() => {
          setSheetOpen(false)
          setSelectedId(null)
        }}
        title={selected ? `${selected.code} · ${selected.type.name}` : 'Объект'}
      >
        {selected ? (
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <div
                className="grid h-12 w-12 shrink-0 place-items-center rounded-xl text-xl"
                style={{ background: `${selected.type.color}22` }}
              >
                {selected.type.icon}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-[17px] font-semibold leading-tight">{selected.name}</div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-ink2">
                  <span className="font-mono">{selected.code}</span>
                  <span
                    className="inline-flex items-center gap-1 rounded-full px-2 py-0.5"
                    style={{
                      background: `${STATUS_COLOR[selected.status]}22`,
                      color: STATUS_COLOR[selected.status],
                    }}
                  >
                    ● {STATUS_LABEL[selected.status] ?? selected.status}
                  </span>
                  {selected.is_mobile ? (
                    <span className="rounded-full bg-surface2 px-2 py-0.5">мобильный</span>
                  ) : null}
                  {selected.grounded ? (
                    <span className="rounded-full bg-ground/20 px-2 py-0.5 text-ground">⏚ заземлено</span>
                  ) : null}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2 text-[13px]">
              <InfoCell label="Координаты" value={
                selected.x !== null && selected.y !== null ? `X ${selected.x} · Y ${selected.y} м` : '—'
              } />
              <InfoCell label="Расположение" value={selected.location_text ?? '—'} />
              <InfoCell label="Входит в" value={selected.parent_name ?? '—'} />
              <InfoCell label="Портов" value={String(selected.ports.length)} />
            </div>

            {Object.keys(selected.attrs ?? {}).length > 0 ? (
              <div>
                <div className="mb-1 text-[12px] uppercase tracking-wide text-ink3">Характеристики</div>
                <div className="grid grid-cols-2 gap-2 text-[13px]">
                  {Object.entries(selected.attrs).map(([key, value]) => (
                    <InfoCell
                      key={key}
                      label={ATTR_LABELS[key] ?? key}
                      value={typeof value === 'boolean' ? (value ? 'да' : 'нет') : String(value)}
                    />
                  ))}
                </div>
              </div>
            ) : null}

            <div>
              <div className="mb-1 text-[12px] uppercase tracking-wide text-ink3">Порты</div>
              <div className="flex flex-wrap gap-1.5">
                {selected.ports.map((port) => (
                  <span
                    key={port.id}
                    className={`rounded-lg border px-2 py-1 text-[12px] ${
                      port.kind === 'in'
                        ? 'border-ok/40 text-ok'
                        : port.kind === 'out'
                          ? 'border-warm/40 text-warm'
                          : 'border-line text-ink2'
                    }`}
                  >
                    {port.code} · {port.name}
                    {port.nominal_voltage_kv && !port.name.includes('кВ')
                      ? ` · ${port.nominal_voltage_kv} кВ`
                      : ''}
                  </span>
                ))}
                {selected.ports.length === 0 ? (
                  <span className="text-[12px] text-ink3">Порты не заданы</span>
                ) : null}
              </div>
            </div>

            {path ? (
              <div>
                <div className="mb-1 text-[12px] uppercase tracking-wide text-ink3">Путь питания</div>
                <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                  {path.source ? (
                    <span className="rounded-lg bg-surface2 px-2 py-1 text-ink2">
                      {path.source.name}
                    </span>
                  ) : null}
                  {path.chain.map((node) => (
                    <span key={`${node.id}-${node.role}`} className="flex items-center gap-1.5">
                      <span className="text-ink3">→</span>
                      <span
                        className={`rounded-lg px-2 py-1 ${
                          node.role === 'asset' ? 'bg-accent/15 text-accent' : 'bg-surface2 text-ink2'
                        }`}
                      >
                        {node.name}
                      </span>
                    </span>
                  ))}
                </div>
                <p className="mt-1 text-[11px] text-ink3">{path.note}</p>
              </div>
            ) : null}

            <div className="flex flex-wrap gap-2 pt-1">
              {isAdmin ? (
                <button
                  type="button"
                  className={confirmDelete ? 'btn-danger' : 'btn-ghost'}
                  onClick={() => void removeSelected()}
                >
                  {confirmDelete ? 'Точно удалить?' : 'Удалить'}
                </button>
              ) : null}
              <button
                type="button"
                className="btn-ghost"
                onClick={() => {
                  setSheetOpen(false)
                  setSelectedId(null)
                }}
              >
                Закрыть
              </button>
            </div>
          </div>
        ) : (
          <div className="py-6 text-center text-[13px] text-ink3">Загружаем карточку…</div>
        )}
      </BottomSheet>

      {/* форма нового объекта */}
      <BottomSheet
        open={sheetOpen && Boolean(draft)}
        onClose={() => {
          setSheetOpen(false)
          setDraft(null)
        }}
        title={draft ? `Новый объект · X ${draft.x} м, Y ${draft.y} м` : 'Новый объект'}
      >
        <div className="space-y-3">
          <label className="block">
            <span className="label">Тип объекта</span>
            <select className="input" value={formType} onChange={(e) => setFormType(e.target.value)}>
              {types.map((type) => (
                <option key={type.code} value={type.code}>
                  {type.icon} {type.name}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="label">Название</span>
            <input
              className="input"
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder="КТП-17"
              autoFocus
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="label">Код (необязательно)</span>
              <input
                className="input font-mono"
                value={formCode}
                onChange={(e) => setFormCode(e.target.value)}
                placeholder="авто"
              />
            </label>
            <label className="block">
              <span className="label">
                {activeType?.attr_schema?.power_kw ? 'Мощность, кВт' : 'Мощность, кВт (опц.)'}
              </span>
              <input
                className="input"
                value={formPower}
                onChange={(e) => setFormPower(e.target.value)}
                inputMode="decimal"
                placeholder="250"
              />
            </label>
          </div>

          <label className="block">
            <span className="label">Расположение</span>
            <input
              className="input"
              value={formLocation}
              onChange={(e) => setFormLocation(e.target.value)}
              placeholder="Гор. +120, борт северный"
            />
          </label>

          {error ? <Alert kind="error">{error}</Alert> : null}

          <div className="flex gap-2 pt-1">
            <button
              type="button"
              className="btn-primary flex-1"
              disabled={saving || formName.trim().length < 2}
              onClick={() => void submitCreate()}
            >
              {saving ? 'Сохраняем…' : 'Создать объект'}
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => {
                setSheetOpen(false)
                setDraft(null)
              }}
            >
              Отмена
            </button>
          </div>
        </div>
      </BottomSheet>
    </div>
  )
}

function InfoCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-surface2/60 px-2.5 py-2">
      <div className="text-[11px] text-ink3">{label}</div>
      <div className="mt-0.5 break-words text-ink">{value}</div>
    </div>
  )
}
