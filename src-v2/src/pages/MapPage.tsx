import { useCallback, useEffect, useMemo, useState, lazy, Suspense } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { AssetSheet } from '../components/asset/AssetSheet'
import { BottomSheet } from '../components/BottomSheet'
import { MapView } from '../components/map/MapView'
import { Alert, Badge } from '../components/ui'
import { ApiError } from '../lib/api'
import type { AssetBrief, AssetType, MapLayer, TopologyGraph } from '../lib/gis'
import { STATUS_COLOR, STATUS_LABEL, gisApi } from '../lib/gis'

// Схема нужна реже карты: грузим React Flow отдельным чанком
const SchemaView = lazy(() =>
  import('../components/map/SchemaView').then((module) => ({ default: module.SchemaView })),
)

type View = 'map' | 'schema'

const CATEGORIES: Array<{ key: string | null; label: string }> = [
  { key: null, label: 'Все' },
  { key: 'source', label: 'Источники' },
  { key: 'equipment', label: 'Оборудование' },
  { key: 'mobile', label: 'Мобильные' },
  { key: 'lighting', label: 'Освещение' },
]

interface PortChoice {
  assetId: string
  assetName: string
  portId: string
  portCode: string
}

export function MapPage() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [view, setView] = useState<View>('map')
  const [layer, setLayer] = useState<MapLayer | null>(null)
  const [assets, setAssets] = useState<AssetBrief[]>([])
  const [types, setTypes] = useState<AssetType[]>([])
  const [graph, setGraph] = useState<TopologyGraph | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [category, setCategory] = useState<string | null>(null)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)

  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState<{ x: number; y: number } | null>(null)
  const [formType, setFormType] = useState('ktp')
  const [formName, setFormName] = useState('')
  const [formCode, setFormCode] = useState('')
  const [formPower, setFormPower] = useState('')
  const [formLocation, setFormLocation] = useState('')
  const [saving, setSaving] = useState(false)

  const [connecting, setConnecting] = useState(false)
  const [connectStep, setConnectStep] = useState<'from' | 'to'>('from')
  const [connectFrom, setConnectFrom] = useState<PortChoice | null>(null)
  const [connectTo, setConnectTo] = useState<PortChoice | null>(null)
  const [connectAssetId, setConnectAssetId] = useState<string | null>(null)
  const [connectPorts, setConnectPorts] = useState<Array<{ id: string; code: string; kind: string; voltage: number | null }>>([])
  const [linkMark, setLinkMark] = useState('')
  const [linkLength, setLinkLength] = useState('')
  const [linkType, setLinkType] = useState('cable')

  const isAdmin = can('asset.create')
  const canSwitch = can('asset.status.edit')
  const canManageDocs = can('document.manage')
  const placeAssetId = (location.state as { placeAssetId?: string } | null)?.placeAssetId ?? null
  const openAssetId = (location.state as { openAssetId?: string } | null)?.openAssetId ?? null

  useEffect(() => {
    if (openAssetId) {
      setSelectedId(openAssetId)
      setSheetOpen(true)
      navigate('.', { replace: true, state: {} })
    }
  }, [openAssetId, navigate])

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

  const loadGraph = useCallback(async () => {
    try {
      const data = await gisApi.graph()
      setGraph(data)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось построить схему')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (view === 'schema' && !graph) void loadGraph()
  }, [view, graph, loadGraph])

  const refresh = useCallback(async () => {
    await load()
    if (view === 'schema') await loadGraph()
  }, [load, loadGraph, view])

  const filtered = useMemo(() => {
    if (!category) return assets
    return assets.filter((asset) => asset.type.category === category)
  }, [assets, category])

  const openAsset = (id: string) => {
    if (connecting) {
      void openConnectPicker(id)
      return
    }
    setSelectedId(id)
    setSheetOpen(true)
  }

  const openConnectPicker = async (id: string) => {
    try {
      const detail = await gisApi.asset(id)
      const ports = detail.ports
        .filter((port) => (connectStep === 'from' ? port.kind !== 'in' : port.kind !== 'out'))
        .map((port) => ({
          id: port.id,
          code: port.code,
          kind: port.kind,
          voltage: port.nominal_voltage_kv,
        }))
      setConnectAssetId(id)
      setConnectPorts(ports)
      setSheetOpen(true)
    } catch {
      setError('Не удалось получить порты объекта')
    }
  }

  const pickPort = async (portId: string, portCode: string) => {
    if (!connectAssetId) return
    const detail = await gisApi.asset(connectAssetId)
    const choice: PortChoice = {
      assetId: connectAssetId,
      assetName: detail.name,
      portId,
      portCode,
    }
    if (connectStep === 'from') {
      setConnectFrom(choice)
      setConnectStep('to')
      setSheetOpen(false)
      setConnectAssetId(null)
    } else if (connectFrom) {
      setConnectTo(choice)
      setConnectAssetId(null)
      setSheetOpen(false)
    }
  }

  const submitLink = async () => {
    if (!connectFrom || !connectTo) return
    setSaving(true)
    setError(null)
    try {
      await gisApi.createLink({
        from_port_id: connectFrom.portId,
        to_port_id: connectTo.portId,
        link_type: linkType,
        cable_mark: linkMark || null,
        length_m: linkLength ? Number(linkLength) : null,
      })
      setConnecting(false)
      setConnectFrom(null)
      setConnectTo(null)
      setConnectStep('from')
      setLinkMark('')
      setLinkLength('')
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать связь')
    } finally {
      setSaving(false)
    }
  }

  const startAdding = () => {
    setAdding(true)
    setDraft(null)
    setSheetOpen(false)
    setConnecting(false)
    setError(null)
  }

  const cancelAdding = () => {
    setAdding(false)
    setDraft(null)
  }

  const handleMapClick = async (x: number, y: number) => {
    const rx = Math.round(x * 10) / 10
    const ry = Math.round(y * 10) / 10

    if (placeAssetId) {
      try {
        await gisApi.update(placeAssetId, { x: rx, y: ry })
        navigate('/registry', { replace: true })
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось разместить объект')
      }
      return
    }

    if (!adding) return
    setDraft({ x: rx, y: ry })
    setSheetOpen(true)
    setFormName('')
    setFormCode('')
    setFormPower('')
    setFormLocation('')
    setFormType(types[0]?.code ?? 'ktp')
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
      await refresh()
      setSelectedId(created.id)
      setSheetOpen(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать объект')
    } finally {
      setSaving(false)
    }
  }

  const cancelConnect = () => {
    setConnecting(false)
    setConnectFrom(null)
    setConnectTo(null)
    setConnectStep('from')
    setConnectAssetId(null)
    setSheetOpen(false)
  }

  const connectAsset = connectAssetId ? assets.find((asset) => asset.id === connectAssetId) : null

  return (
    <div className="absolute inset-0 overflow-hidden bg-[#070C10]">
      {view === 'map' ? (
        layer ? (
          <MapView
            layer={layer}
            assets={filtered}
            selectedId={selectedId}
            onSelect={openAsset}
            adding={adding || Boolean(placeAssetId)}
            onMapClick={handleMapClick}
            draft={draft}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-ink2">
            {loading ? 'Загружаем карту…' : 'Карта недоступна'}
          </div>
        )
      ) : graph ? (
        <Suspense fallback={<div className="flex h-full items-center justify-center text-ink2">Строим схему…</div>}>
          <SchemaView graph={graph} selectedId={selectedId} onSelect={openAsset} />
        </Suspense>
      ) : (
        <div className="flex h-full items-center justify-center text-ink2">Строим схему…</div>
      )}

      {/* верхняя панель: вид + фильтры */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-[1000] p-3">
        <div className="pointer-events-auto flex flex-wrap items-center gap-2">
          <div className="flex rounded-full border border-line bg-bg/85 p-1 backdrop-blur">
            <button
              type="button"
              onClick={() => setView('map')}
              className={`rounded-full px-3 py-1.5 text-[12px] ${view === 'map' ? 'bg-accent text-[#08131F]' : 'text-ink2'}`}
            >
              Карта
            </button>
            <button
              type="button"
              onClick={() => setView('schema')}
              className={`rounded-full px-3 py-1.5 text-[12px] ${view === 'schema' ? 'bg-accent text-[#08131F]' : 'text-ink2'}`}
            >
              Схема
            </button>
          </div>

          {view === 'map' ? (
            <div className="flex max-w-full gap-1 overflow-x-auto rounded-full border border-line bg-bg/85 p-1 backdrop-blur [scrollbar-width:none]">
              {CATEGORIES.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => setCategory(item.key)}
                  className={`whitespace-nowrap rounded-full px-3 py-1.5 text-[12px] ${
                    category === item.key ? 'bg-accent text-[#08131F]' : 'text-ink2 hover:text-ink'
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ) : null}

          <span className="rounded-full border border-line bg-bg/85 px-3 py-1.5 text-[12px] text-ink2 backdrop-blur">
            {view === 'map' ? `${filtered.length} из ${assets.length}` : `${graph?.nodes.length ?? 0} узлов`}
          </span>
        </div>

        {placeAssetId ? (
          <div className="pointer-events-auto mt-2 flex items-center justify-between gap-3 rounded-xl border border-accent/40 bg-accent/10 px-3 py-2 text-[13px] text-accent backdrop-blur">
            <span>Кликните по карте, чтобы разместить объект</span>
            <button type="button" className="text-[12px] underline" onClick={() => navigate('/registry')}>
              Отмена
            </button>
          </div>
        ) : null}

        {connecting ? (
          <div className="pointer-events-auto mt-2 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-accent/40 bg-accent/10 px-3 py-2 text-[13px] text-accent backdrop-blur">
            <span>
              {connectStep === 'from'
                ? 'Соединение: выберите объект-источник и его порт OUT'
                : `Соединение: ${connectFrom?.assetName} ${connectFrom?.portCode} → выберите объект и порт IN`}
            </span>
            <button type="button" className="text-[12px] underline" onClick={cancelConnect}>
              Отмена
            </button>
          </div>
        ) : null}

        {adding ? (
          <div className="pointer-events-auto mt-2 flex items-center justify-between gap-3 rounded-xl border border-accent/40 bg-accent/10 px-3 py-2 text-[13px] text-accent backdrop-blur">
            <span>
              {draft ? `Точка: X ${draft.x} м, Y ${draft.y} м` : 'Кликните по карте, чтобы поставить объект'}
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

      {view === 'map' ? (
        <div className="pointer-events-none absolute bottom-4 left-3 z-[1000] hidden rounded-xl border border-line bg-bg/85 p-3 text-[11px] backdrop-blur sm:block">
          <div className="mb-1.5 text-ink3">Состояние</div>
          {['on', 'off', 'standby', 'maintenance'].map((status) => (
            <div key={status} className="flex items-center gap-2 py-0.5 text-ink2">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: STATUS_COLOR[status] }} />
              {STATUS_LABEL[status]}
            </div>
          ))}
        </div>
      ) : (
        <div className="pointer-events-none absolute bottom-4 left-3 z-[1000] hidden rounded-xl border border-line bg-bg/85 p-3 text-[11px] backdrop-blur sm:block">
          <div className="mb-1.5 text-ink3">Обозначения</div>
          <div className="text-ink2">— сплошная: связь включена</div>
          <div className="text-ink2">┄ пунктир: разомкнута</div>
          <div className="text-ink2">⏚ заземлено · фиолетовая: перемычка</div>
        </div>
      )}

      {isAdmin && view === 'map' && !adding ? (
        <div className="absolute bottom-5 right-4 z-[1000] flex gap-2">
          <button
            type="button"
            onClick={() => {
              setConnecting((prev) => !prev)
              setConnectStep('from')
              setConnectFrom(null)
              setError(null)
            }}
            className={`flex h-12 items-center gap-2 rounded-full border px-4 text-[13px] font-semibold ${
              connecting ? 'border-accent bg-accent text-[#08131F]' : 'border-line bg-bg/90 text-ink'
            }`}
          >
            🔗 Соединить
          </button>
          <button
            type="button"
            onClick={startAdding}
            className="flex h-12 items-center gap-2 rounded-full bg-accent px-5 text-[14px] font-semibold text-[#08131F] shadow-lg active:scale-[0.98]"
          >
            <span className="text-xl leading-none">＋</span> Объект
          </button>
        </div>
      ) : null}

      {/* карточка объекта */}
      <BottomSheet
        open={sheetOpen && !draft && !connectAssetId}
        onClose={() => {
          setSheetOpen(false)
          setSelectedId(null)
        }}
        title="Объект"
      >
        {selectedId ? (
          <AssetSheet
            assetId={selectedId}
            onOpenAsset={(id) => setSelectedId(id)}
            canManage={can('asset.create')}
            canSwitch={canSwitch}
            canManageDocs={canManageDocs}
          />
        ) : null}
      </BottomSheet>

      {/* выбор порта при соединении */}
      <BottomSheet
        open={sheetOpen && Boolean(connectAssetId)}
        onClose={() => setSheetOpen(false)}
        title={
          connectAsset
            ? `${connectAsset.code} · выберите порт ${connectStep === 'from' ? 'OUT' : 'IN'}`
            : 'Порт'
        }
      >
        <div className="space-y-3">
          <p className="hint">
            {connectStep === 'from'
              ? 'Порт, от которого идёт питание (OUT или двунаправленный).'
              : 'Порт, на который приходит питание (IN или двунаправленный).'}
          </p>
          <div className="flex flex-wrap gap-2">
            {connectPorts.map((port) => (
              <button
                key={port.id}
                type="button"
                className="rounded-xl border border-line bg-surface2 px-3 py-2 text-left text-[13px] hover:border-accent"
                onClick={() => void pickPort(port.id, port.code)}
              >
                <div className="font-mono">{port.code}</div>
                <div className="text-[11px] text-ink3">{port.voltage ? `${port.voltage} кВ` : port.kind}</div>
              </button>
            ))}
            {connectPorts.length === 0 ? (
              <p className="text-[13px] text-ink3">У объекта нет подходящих портов</p>
            ) : null}
          </div>
        </div>
      </BottomSheet>

      {/* форма параметров связи */}
      <BottomSheet
        open={Boolean(connectFrom && connectTo)}
        onClose={cancelConnect}
        title="Параметры связи"
      >
        <div className="space-y-3">
          <div className="rounded-xl bg-surface2/60 px-3 py-2 text-[13px]">
            <div>
              <span className="text-ink3">от </span>
              <span className="font-mono">{connectFrom?.assetName}</span> {connectFrom?.portCode}
            </div>
            <div className="mt-1">
              <span className="text-ink3">к </span>
              <span className="font-mono">{connectTo?.assetName}</span> {connectTo?.portCode}
            </div>
          </div>
          <label className="block">
            <span className="label">Тип связи</span>
            <select className="input" value={linkType} onChange={(e) => setLinkType(e.target.value)}>
              <option value="cable">Кабель</option>
              <option value="overhead">Воздушная линия</option>
              <option value="busbar">Шина</option>
              <option value="jumper">Перемычка</option>
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="label">Марка</span>
              <input
                className="input"
                value={linkMark}
                onChange={(e) => setLinkMark(e.target.value)}
                placeholder="СБ-3×50"
              />
            </label>
            <label className="block">
              <span className="label">Длина, м</span>
              <input
                className="input"
                value={linkLength}
                onChange={(e) => setLinkLength(e.target.value)}
                inputMode="decimal"
                placeholder="120"
              />
            </label>
          </div>
          {error ? <Alert kind="error">{error}</Alert> : null}
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-primary flex-1"
              disabled={saving}
              onClick={() => void submitLink()}
            >
              {saving ? 'Создаём…' : 'Создать связь'}
            </button>
            <button type="button" className="btn-ghost" onClick={cancelConnect}>
              Отмена
            </button>
          </div>
        </div>
      </BottomSheet>

      {/* создание объекта */}
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
              <span className="label">Мощность, кВт</span>
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
          <div className="flex gap-2">
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

      {connecting && connectStep === 'to' ? (
        <div className="pointer-events-none absolute inset-x-0 bottom-24 z-[1000] flex justify-center">
          <Badge tone="accent">
            Выберите на карте объект-приёмник · отмена — в панели сверху
          </Badge>
        </div>
      ) : null}
    </div>
  )
}
