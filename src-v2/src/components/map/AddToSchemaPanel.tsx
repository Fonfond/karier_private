import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError } from '../../lib/api'
import { gisApi } from '../../lib/gis'
import type { AssetBrief, AssetType } from '../../lib/gis'

type Tab = 'registry' | 'type' | 'contour' | 'equipment'

/**
 * Быстрое добавление на схему: объект из реестра, новый объект по типу
 * или прямоугольный контур.
 *
 * Всё, что создаётся здесь, сразу попадает в реестр `gis.assets` — схема
 * не держит «виртуальных» узлов. Отмену/повтор ведёт SchemaView через
 * колбэки: панель не знает про историю.
 */
export function AddToSchemaPanel({
  open,
  onClose,
  center,
  onCreatedAsset,
  onPlaced,
  onLineEquipment,
}: {
  open: boolean
  onClose: () => void
  center: { x: number; y: number }
  onCreatedAsset: (id: string, title: string) => void
  onPlaced: (id: string, x: number, y: number, previous: { x: number; y: number } | null) => void
  onLineEquipment: (assetId: string, linkId: string | null, title: string) => void
}) {
  const [tab, setTab] = useState<Tab>('registry')
  const [types, setTypes] = useState<AssetType[]>([])
  const [assets, setAssets] = useState<AssetBrief[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [typeCode, setTypeCode] = useState('')
  const [newName, setNewName] = useState('')
  const [contourName, setContourName] = useState('')
  const [anchor, setAnchor] = useState<{ id: string; name: string; code: string } | null>(null)
  const [equipmentType, setEquipmentType] = useState('')
  const [equipmentName, setEquipmentName] = useState('')
  const [equipmentCable, setEquipmentCable] = useState('')
  const [contourType, setContourType] = useState('')
  const [width, setWidth] = useState('360')
  const [height, setHeight] = useState('240')

  const load = useCallback(async (query: string) => {
    setLoading(true)
    setError(null)
    try {
      const [typeList, assetList] = await Promise.all([
        gisApi.types(),
        gisApi.assets(query ? { q: query } : {}),
      ])
      setTypes(typeList)
      setAssets(assetList.items)
      if (!typeCode && typeList.length > 0) {
        const simple = typeList.find((item) => !item.is_composite) ?? typeList[0]
        setTypeCode(simple.code)
        setContourType(simple.code)
        const equipment = typeList.find((item) => /ктп|яку|разъед|рлнд|ktp|yaku/i.test(item.name + item.code)) ?? simple
        setEquipmentType(equipment.code)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить справочники')
    } finally {
      setLoading(false)
    }
  }, [typeCode])

  useEffect(() => {
    if (open) void load(search)
    // поиск применяем по кнопке/Enter, чтобы не дёргать API на каждый символ
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return assets
    return assets.filter(
      (item) =>
        item.code.toLowerCase().includes(query) || item.name.toLowerCase().includes(query),
    )
  }, [assets, search])

  const placeExisting = async (item: AssetBrief) => {
    setSaving(true)
    setError(null)
    try {
      const asset = await gisApi.asset(item.id)
      const previous =
        asset.schema_x != null && asset.schema_y != null
          ? { x: asset.schema_x, y: asset.schema_y }
          : null
      await gisApi.placeOnSchema(item.id, center.x, center.y)
      onPlaced(item.id, center.x, center.y, previous)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось поставить объект на схему')
    } finally {
      setSaving(false)
    }
  }

  const createByType = async () => {
    const name = newName.trim() || types.find((item) => item.code === typeCode)?.name || ''
    if (!typeCode || name.length < 2) {
      setError('Выберите тип и укажите название (минимум 2 символа)')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const asset = await gisApi.create({ name, type_code: typeCode })
      await gisApi.placeOnSchema(asset.id, center.x, center.y)
      onCreatedAsset(asset.id, asset.name)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать объект')
    } finally {
      setSaving(false)
    }
  }

  const addEquipment = async () => {
    if (!anchor) {
      setError('Выберите опору или узел, к которому присоединить оборудование')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const result = await gisApi.addLineEquipment({
        anchor_asset_id: anchor.id,
        type_code: equipmentType,
        name: equipmentName.trim() || undefined,
        cable_mark: equipmentCable.trim() || undefined,
      })
      onLineEquipment(result.asset_id, result.link_id, result.name)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось добавить оборудование')
    } finally {
      setSaving(false)
    }
  }
  const createContour = async () => {
    const name = contourName.trim()
    if (name.length < 2 || !contourType) {
      setError('Укажите название контура и тип')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const contour = await gisApi.createContour({
        name,
        type_code: contourType,
        x: center.x,
        y: center.y,
        width: Number(width) || 360,
        height: Number(height) || 240,
      })
      onCreatedAsset(contour.id, contour.name)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать контур')
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null

  const tabButton = (value: Tab, title: string) => (
    <button
      type="button"
      className={
        tab === value
          ? 'rounded-lg bg-accent/20 px-2 py-1 text-[12px] text-accent'
          : 'rounded-lg px-2 py-1 text-[12px] text-ink3 hover:bg-surface2'
      }
      onClick={() => setTab(value)}
    >
      {title}
    </button>
  )

  return (
    <div className="fixed inset-0 z-[1500] flex items-end justify-center bg-black/60 p-3 sm:items-center">
      <div className="card modal-safe flex max-h-[92vh] w-full max-w-xl flex-col p-4 text-[13px]">
        <div className="mb-2 flex items-start justify-between gap-2">
          <div>
            <div className="text-[15px] font-semibold">Добавить на схему</div>
            <div className="text-[11px] text-ink3">
              Новые объекты сразу попадают в реестр. Библиотека блоков — отдельной панелью слева.
            </div>
          </div>
          <button type="button" className="btn-ghost h-8 px-2" onClick={onClose} title="Закрыть">
            ✕
          </button>
        </div>

        <div className="mb-2 flex gap-1">
          {tabButton('registry', 'Из реестра')}
          {tabButton('type', 'По типу')}
          {tabButton('contour', 'Контур')}
          {tabButton('equipment', 'Оборудование линии')}
        </div>

        {error ? (
          <div className="mb-2 rounded border border-danger/40 p-2 text-[12px] text-danger">{error}</div>
        ) : null}

        <div className="min-h-0 flex-1 overflow-y-auto">
          {tab === 'registry' ? (
            <div>
              <div className="mb-2 flex gap-2">
                <input
                  className="input h-8"
                  placeholder="Поиск по коду или названию"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void load(search)
                  }}
                />
                <button type="button" className="btn-ghost h-8 px-2" onClick={() => void load(search)}>
                  Найти
                </button>
              </div>
              {loading ? <div className="p-2 text-[12px] text-ink3">Загрузка…</div> : null}
              {filtered.map((item) => (
                <div
                  key={item.id}
                  className="mb-1 flex items-center justify-between gap-2 rounded-lg border border-line px-2 py-1.5"
                >
                  <div className="min-w-0">
                    <div className="truncate text-[12px] font-semibold">{item.name}</div>
                    <div className="text-[11px] text-ink3">
                      {item.code} · {item.type.name}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="btn-ghost h-7 shrink-0 px-2"
                    disabled={saving}
                    onClick={() => void placeExisting(item)}
                  >
                    На схему
                  </button>
                </div>
              ))}
              {!loading && filtered.length === 0 ? (
                <div className="p-2 text-[12px] text-ink3">Ничего не найдено.</div>
              ) : null}
            </div>
          ) : null}

          {tab === 'type' ? (
            <div className="space-y-2">
              <label className="block text-[11px] text-ink3">
                Тип объекта
                <select
                  className="input mt-1 h-8"
                  value={typeCode}
                  onChange={(event) => setTypeCode(event.target.value)}
                >
                  {types.map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-[11px] text-ink3">
                Название
                <input
                  className="input mt-1 h-8"
                  value={newName}
                  placeholder="Например: КТП-15"
                  onChange={(event) => setNewName(event.target.value)}
                />
              </label>
              <p className="text-[11px] text-ink3">
                Объект создаётся в реестре (код сгенерируется), получает порты по шаблону типа
                и ставится в центр схемы. Дальше его можно двигать и соединять.
              </p>
              <button type="button" className="btn-primary h-8 px-3" disabled={saving} onClick={createByType}>
                Создать и поставить
              </button>
            </div>
          ) : null}

          {tab === 'contour' ? (
            <div className="space-y-2">
              <label className="block text-[11px] text-ink3">
                Название контура
                <input
                  className="input mt-1 h-8"
                  value={contourName}
                  placeholder="Например: РУ-2 (новый корпус)"
                  onChange={(event) => setContourName(event.target.value)}
                />
              </label>
              <label className="block text-[11px] text-ink3">
                Тип объекта контура
                <select
                  className="input mt-1 h-8"
                  value={contourType}
                  onChange={(event) => setContourType(event.target.value)}
                >
                  {types.map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[11px] text-ink3">
                  Ширина, px
                  <input
                    className="input mt-1 h-8"
                    inputMode="numeric"
                    value={width}
                    onChange={(event) => setWidth(event.target.value)}
                  />
                </label>
                <label className="text-[11px] text-ink3">
                  Высота, px
                  <input
                    className="input mt-1 h-8"
                    inputMode="numeric"
                    value={height}
                    onChange={(event) => setHeight(event.target.value)}
                  />
                </label>
              </div>
              <p className="text-[11px] text-ink3">
                Прямоугольник-контур создаётся как объект реестра с типом и портами; внутри него
                кнопкой «+ ячейка» добавляются ячейки, между ними — перемычки.
              </p>
              <button type="button" className="btn-primary h-8 px-3" disabled={saving} onClick={createContour}>
                Создать контур
              </button>
            </div>
          ) : null}
          {tab === 'equipment' ? (
            <div className="space-y-2">
              <p className="text-[11px] text-ink3">
                Оборудование создаётся в реестре и сразу присоединяется кабелем к выбранной опоре/узлу.
                Дальше в карточке объекта можно загрузить схему, паспорт и уставки.
              </p>
              <label className="block text-[11px] text-ink3">
                Присоединить к опоре/узлу
                <input
                  className="input mt-1 h-8"
                  placeholder="Поиск по коду или названию"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
              <div className="max-h-40 overflow-y-auto rounded-lg border border-line">
                {filtered.slice(0, 30).map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left text-[12px] hover:bg-surface2 ${
                      anchor?.id === item.id ? 'bg-accent/15' : ''
                    }`}
                    onClick={() => setAnchor({ id: item.id, name: item.name, code: item.code })}
                  >
                    <span className="truncate">{item.name}</span>
                    <span className="shrink-0 text-[10px] text-ink3">{item.code}</span>
                  </button>
                ))}
              </div>
              {anchor ? (
                <div className="text-[11px] text-ok">Выбрано: {anchor.name} ({anchor.code})</div>
              ) : (
                <div className="text-[11px] text-ink3">Опора не выбрана</div>
              )}
              <label className="block text-[11px] text-ink3">
                Тип оборудования
                <select
                  className="input mt-1 h-8"
                  value={equipmentType}
                  onChange={(event) => setEquipmentType(event.target.value)}
                >
                  {types.map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="text-[11px] text-ink3">
                  Название (необязательно)
                  <input
                    className="input mt-1 h-8"
                    value={equipmentName}
                    placeholder="КТП-15"
                    onChange={(event) => setEquipmentName(event.target.value)}
                  />
                </label>
                <label className="text-[11px] text-ink3">
                  Марка кабеля
                  <input
                    className="input mt-1 h-8"
                    value={equipmentCable}
                    placeholder="Ф-15К"
                    onChange={(event) => setEquipmentCable(event.target.value)}
                  />
                </label>
              </div>
              <button type="button" className="btn-primary h-8 px-3" disabled={saving} onClick={addEquipment}>
                Добавить в линию
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
