import { useCallback, useEffect, useMemo, useState, lazy, Suspense } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { AssetSheet } from '../components/asset/AssetSheet'
import { BottomSheet } from '../components/BottomSheet'
import { MapView } from '../components/map/MapView'
import { Alert, Badge, ConfirmDialog } from '../components/ui'
import { ApiError } from '../lib/api'
import type { AssetBrief, AssetType, ChildAsset, MapLayer, TopologyGraph } from '../lib/gis'
import { POWER_COLOR, gisApi } from '../lib/gis'
import { applyPowerState, powerStateOf } from '../lib/power'
import type { PowerStateUpdate } from '../lib/power'
import { enqueue } from '../lib/outbox'
import { syncOutbox } from '../lib/sync'
import { syncApi } from '../lib/syncApi'

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

  const [searchParams, setSearchParams] = useSearchParams()
  const routeView: View = searchParams.get('view') === 'schema' ? 'schema' : 'map'
  const [view, setView] = useState<View>(() => (searchParams.get('view') === 'schema' ? 'schema' : 'map'))
  // 38a: на мобильном переключатель Карта/Схема живёт в шапке (AppShell) и меняет URL —
  // страница должна следовать за адресом, а не только за собственным состоянием.
  useEffect(() => {
    setView(routeView)
  }, [routeView])
  const [layer, setLayer] = useState<MapLayer | null>(null)
  const [mapOpen, setMapOpen] = useState(false)
  const [mapFile, setMapFile] = useState<File | null>(null)
  const [mapSaving, setMapSaving] = useState(false)
  const [mapError, setMapError] = useState<string | null>(null)
  const [mapForm, setMapForm] = useState({ name: 'Новая карта', mpp: '0.5', ox: '0', oy: '0' })
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
  const [placePickerOpen, setPlacePickerOpen] = useState(false)
  const [vlMode, setVlMode] = useState(false)
  const [vlPath, setVlPath] = useState<Array<{ x: number; y: number }>>([])
  const [vlDialog, setVlDialog] = useState(false)
  const [vlSaving, setVlSaving] = useState(false)
  const [hint, setHint] = useState<string | null>(null)
  const [compositeDialog, setCompositeDialog] = useState(false)
  const [compositeTypeId, setCompositeTypeId] = useState('')
  const [compositeMode, setCompositeMode] = useState(false)
  const [vlForm, setVlForm] = useState({ count: '5', start: '1', step: '1', prefix: 'оп.', sourceId: '', targetId: '' })
  const [placeQuery, setPlaceQuery] = useState('')

  const [connecting, setConnecting] = useState(false)
  const [connectStep, setConnectStep] = useState<'from' | 'to'>('from')
  const [connectFrom, setConnectFrom] = useState<PortChoice | null>(null)
  const [connectTo, setConnectTo] = useState<PortChoice | null>(null)
  const [connectAssetId, setConnectAssetId] = useState<string | null>(null)
  const [connectPorts, setConnectPorts] = useState<Array<{ id: string; code: string; kind: string; voltage: number | null }>>([])
  const [connectChildren, setConnectChildren] = useState<ChildAsset[]>([])
  const [connectChild, setConnectChild] = useState<{ id: string; name: string } | null>(null)
  const [connectBlockId, setConnectBlockId] = useState<string | null>(null)
  const [linkMark, setLinkMark] = useState('')
  const [linkLength, setLinkLength] = useState('')
  const [linkType, setLinkType] = useState('cable')
  const [linkMode, setLinkMode] = useState(false)
  const [dragFrom, setDragFrom] = useState<string | null>(null)
  const [editLink, setEditLink] = useState<{ id: string; type: string; mark: string; no: string; status: string; installed: string; length: string; state: string } | null>(null)
  const [linkSaving, setLinkSaving] = useState(false)
  const [confirmRemoveLink, setConfirmRemoveLink] = useState(false)

  const [movingAsset, setMovingAsset] = useState<AssetBrief | null>(null)
  const [moveDraft, setMoveDraft] = useState<{ x: number; y: number } | null>(null)
  const [moveNote, setMoveNote] = useState('')
  const [moveHistory, setMoveHistory] = useState<Array<{ x: number; y: number }>>([])
  const [moveSaving, setMoveSaving] = useState(false)

  const isAdmin = can('asset.create')
  const canSwitch = can('asset.status.edit')
  const canManageDocs = can('document.manage')
  const placeAssetId = (location.state as { placeAssetId?: string } | null)?.placeAssetId ?? null
  const openAssetId = (location.state as { openAssetId?: string } | null)?.openAssetId ?? null

  useEffect(() => {
    if (!vlMode) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Enter') {
        event.preventDefault()
        void finishVl()
      }
      if (event.key === 'Escape') {
        setVlMode(false)
        setVlPath([])
        setVlDialog(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [vlMode, vlPath, vlForm])

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
    if (!graph) void loadGraph()
  }, [view, graph, loadGraph])

  const refresh = useCallback(async () => {
    await load()
    await loadGraph()
  }, [load, loadGraph, view])

  /**
   * F1: успешное переключение из карточки объекта.
   *
   * 1. Сразу правим локальный реестр `assets` — SchemaView строит `assetStates`
   *    из него и перекрашивает ячейку (красный ↔ зелёный) без перезагрузки.
   * 2. Тихо перечитываем граф, чтобы обновились статусы одиночных узлов
   *    (например, разъединителя КТП, если он вне блока). Камеру не сбрасываем:
   *    SchemaView делает fitView только при первом открытии схемы.
   */
  const handleStateChanged = useCallback(
    (update: PowerStateUpdate) => {
      // точечный override — работает даже для только что созданных ячеек
      setPowerOverrides((prev) => ({
        ...prev,
        [update.id]: { status: update.status, grounded: update.grounded },
      }))
      setAssets((prev) => applyPowerState(prev, update))
      void loadGraph()
    },
    [loadGraph],
  )

  const filtered = useMemo(() => {
    const visible = assets.filter((asset) => !asset.grouped)
    if (!category) return visible
    return visible.filter((asset) => asset.type.category === category)
  }, [assets, category])

  /**
   * Статусы ячеек для блоков схемы. Граф отдаёт состав блока без статуса, а реестр
   * (`assets`) уже загружен — берём оттуда, чтобы не делать запрос на каждую ячейку.
   *
   * `powerOverrides` — точечные результаты переключений (F1). Они нужны для ячеек,
   * которых ещё нет в загруженном реестре: например, блок только что создан
   * мастером «По шаблону», и карточка ячейки открыта до перезагрузки списка.
   */
  const [powerOverrides, setPowerOverrides] = useState<Record<string, { status: string; grounded: boolean }>>({})

  const assetStates = useMemo(() => {
    const result: Record<string, { status: string; grounded: boolean }> = { ...powerOverrides }
    for (const asset of assets) {
      if (asset.cell_kind) result[asset.id] = { status: asset.status, grounded: asset.grounded }
    }
    return result
  }, [assets, powerOverrides])

  const openAsset = (id: string) => {
    if (movingAsset) return
    if (linkMode) {
      // В режиме связи клик по объекту открывает выбор порта/ячейки,
      // а не карточку: для комплекса сначала выбирается ячейка.
      void openConnectPicker(id)
      return
    }
    if (connecting) {
      void openConnectPicker(id)
      return
    }
    setSelectedId(id)
    setSheetOpen(true)
    void gisApi
      .asset(id)
      .then((detail) => {
        if (!detail.is_mobile) {
          setMoveHistory([])
          return
        }
        return syncApi.moves(id).then((data) => {
          setMoveHistory(
            data.items
              .slice()
              .reverse()
              .flatMap((move) => {
                const points: Array<{ x: number; y: number }> = []
                if (move.from_x !== null && move.from_y !== null) points.push({ x: move.from_x, y: move.from_y })
                points.push({ x: move.to_x, y: move.to_y })
                return points
              }),
          )
        })
      })
      .catch(() => setMoveHistory([]))
  }

  const openConnectPicker = async (id: string) => {
    try {
      const [detail, children] = await Promise.all([
        gisApi.asset(id),
        gisApi.children(id).catch(() => [] as ChildAsset[]),
      ])
      const ports = detail.ports
        .filter((port) => (connectStep === 'from' ? port.kind !== 'in' : port.kind !== 'out'))
        .map((port) => ({
          id: port.id,
          code: port.code,
          kind: port.kind,
          voltage: port.nominal_voltage_kv,
        }))
      setConnectBlockId(id)
      setConnectChildren(children)
      setConnectChild(null)
      setConnectAssetId(id)
      setConnectPorts(ports)
      setSheetOpen(true)
    } catch {
      setError('Не удалось получить порты объекта')
    }
  }

  const pickChildPorts = (child: ChildAsset) => {
    const ports = child.ports
      .filter((port) => (connectStep === 'from' ? port.kind !== 'in' : port.kind !== 'out'))
      .map((port) => ({
        id: port.id,
        code: port.code,
        kind: port.kind,
        voltage: port.nominal_voltage_kv,
      }))
    setConnectAssetId(child.id)
    setConnectChild({ id: child.id, name: child.name })
    setConnectPorts(ports)
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

  const startLinkDrag = (id: string) => {
    if (!linkMode) return
    if (!dragFrom) {
      setDragFrom(id)
      return
    }
    // второй клик по другому объекту — соединяем (без обязательного перетаскивания)
    if (dragFrom !== id) void dropLinkDrag(id)
  }

  const dropLinkDrag = async (id: string) => {
    if (!linkMode || !dragFrom || id === dragFrom) return
    const sourceId = dragFrom
    setDragFrom(null)
    try {
      let [source, target] = await Promise.all([gisApi.asset(sourceId), gisApi.asset(id)])
      // Если комплекс содержит ячейки — не соединяем «комплекс целиком»,
      // а предлагаем выбрать конкретную ячейку (её порт).
      const [sourceKids, targetKids] = await Promise.all([
        gisApi.children(sourceId).catch(() => [] as ChildAsset[]),
        gisApi.children(id).catch(() => [] as ChildAsset[]),
      ])
      if (sourceKids.length > 0 || targetKids.length > 0) {
        setConnecting(true)
        setConnectStep('from')
        setConnectFrom(null)
        setConnectTo(null)
        setError(null)
        void openConnectPicker(sourceKids.length > 0 ? sourceId : id)
        return
      }
      let fromPort = source.ports.find((port) => port.kind !== 'in')
      let toPort = target.ports.find((port) => port.kind !== 'out')
      if (!fromPort || !toPort) {
        // у объектов, созданных без шаблона портов, создаём вход/выход автоматически
        await Promise.all([gisApi.ensurePorts(sourceId), gisApi.ensurePorts(id)])
        ;[source, target] = await Promise.all([gisApi.asset(sourceId), gisApi.asset(id)])
        fromPort = source.ports.find((port) => port.kind !== 'in')
        toPort = target.ports.find((port) => port.kind !== 'out')
      }
      if (!fromPort || !toPort) {
        setError('У одного из объектов нет подходящих портов для связи')
        return
      }
      if (fromPort.kind === 'in' || toPort.kind === 'out') {
        setError('Соединять можно только выход со входом (OUT → IN)')
        return
      }
      const fromKv = fromPort.nominal_voltage_kv
      const toKv = toPort.nominal_voltage_kv
      if (fromKv != null && toKv != null && fromKv !== toKv) {
        setError(`Напряжения не совпадают: ${fromKv} кВ и ${toKv} кВ`)
        return
      }
      setConnectFrom({ assetId: source.id, assetName: source.name, portId: fromPort.id, portCode: fromPort.code })
      setConnectTo({ assetId: target.id, assetName: target.name, portId: toPort.id, portCode: toPort.code })
      setConnecting(true)
      setConnectStep('from')
      setError(null)
    } catch {
      setError('Не удалось получить порты объектов')
    }
  }

  const openLinkEditor = (id: string) => {
    const edge = graph?.edges.find((item) => item.id === id)
    if (!edge) return
    setEditLink({
      id,
      type: edge.link_type,
      mark: edge.cable_mark ?? '',
      no: edge.cable_no ?? '',
      status: edge.cable_status ?? 'in_work',
      installed: edge.installed_on ?? '',
      length: edge.length_m != null ? String(edge.length_m) : '',
      state: edge.state,
    })
  }

  const saveLinkEdit = async () => {
    if (!editLink) return
    setLinkSaving(true)
    try {
      await gisApi.updateLink(editLink.id, {
        link_type: editLink.type,
        cable_mark: editLink.mark || null,
        cable_no: editLink.no || null,
        cable_status: editLink.status,
        installed_on: editLink.installed || null,
        length_m: editLink.length ? Number(editLink.length) : null,
        state: editLink.state,
      })
      setEditLink(null)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить связь')
    } finally {
      setLinkSaving(false)
    }
  }

  const removeLink = async () => {
    if (!editLink) return
    setLinkSaving(true)
    try {
      await gisApi.deleteLink(editLink.id)
      setEditLink(null)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось удалить связь')
    } finally {
      setLinkSaving(false)
    }
  }

  const startVl = () => {
    setAdding(false)
    setDraft(null)
    setLinkMode(false)
    setConnecting(false)
    setVlPath([])
    setVlMode(true)
    setVlDialog(true)
  }

  const finishVl = async () => {
    const source = vlForm.sourceId ? assets.find((item) => item.id === vlForm.sourceId) : null
    const target = vlForm.targetId ? assets.find((item) => item.id === vlForm.targetId) : null
    const direct =
      source && target && source.x != null && source.y != null && target.x != null && target.y != null
    let pathPoints = vlPath
    if (!direct && pathPoints.length < 2) {
      setError('Поставьте минимум две точки линии или выберите оборудование «откуда» и «куда»')
      return
    }
    if (direct && pathPoints.length === 0) {
      pathPoints = [
        { x: source!.x as number, y: source!.y as number },
        { x: target!.x as number, y: target!.y as number },
      ]
    }
    setVlSaving(true)
    try {
      const result = await gisApi.generatePoles({
        type_code: 'op',
        x1: pathPoints[0].x,
        y1: pathPoints[0].y,
        x2: pathPoints[pathPoints.length - 1].x,
        y2: pathPoints[pathPoints.length - 1].y,
        count: Math.max(1, Number(vlForm.count) || 1),
        start: Number(vlForm.start) || 1,
        step: Math.max(1, Number(vlForm.step) || 1),
        prefix: vlForm.prefix || 'оп.',
        source_asset_id: vlForm.sourceId || undefined,
        target_asset_id: vlForm.targetId || undefined,
        path: pathPoints.map((point) => [point.x, point.y]),
      })
      setVlMode(false)
      setVlPath([])
      setHint(`ВЛ построена: ${result.count} опор (${result.first}…${result.last})`)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось построить ВЛ')
    } finally {
      setVlSaving(false)
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

    if (compositeMode && compositeTypeId) {
      setSaving(true)
      try {
        const result = await gisApi.placeComposite({ type_id: compositeTypeId, x: rx, y: ry })
        setHint(`Размещён комплект «${result.name}»: ${result.children} ячеек`)
        setCompositeMode(false)
        await refresh()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось разместить комплект')
      } finally {
        setSaving(false)
      }
      return
    }

    if (vlMode) {
      setVlPath((current) => [...current, { x: rx, y: ry }])
      setHint(`Точек: ${vlPath.length + 1}. Enter или «Завершить» — построить ВЛ`)
      return
    }

    if (movingAsset) {
      setMoveDraft({ x: rx, y: ry })
      setSheetOpen(true)
      return
    }

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
    setPlaceQuery('')
    setPlacePickerOpen(true)
    setSheetOpen(false)
    setFormName('')
    setFormCode('')
    setFormPower('')
    setFormLocation('')
    setFormType(types[0]?.code ?? 'ktp')
  }

  const placeExisting = async (id: string) => {
    if (!draft) return
    setSaving(true)
    try {
      await gisApi.update(id, { x: draft.x, y: draft.y })
      setPlacePickerOpen(false)
      setDraft(null)
      setAdding(false)
      await refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось разместить объект')
    } finally {
      setSaving(false)
    }
  }

  const placePickerItems = (() => {
    const query = placeQuery.trim().toLowerCase()
    return assets
      .filter(
        (asset) =>
          !query ||
          asset.name.toLowerCase().includes(query) ||
          asset.code.toLowerCase().includes(query),
      )
      .slice()
      .sort((a, b) => {
        const left = a.x === null ? 0 : 1
        const right = b.x === null ? 0 : 1
        if (left !== right) return left - right
        return a.name.localeCompare(b.name, 'ru')
      })
  })()

  const handleAssetDrop = async (id: string, x: number, y: number) => {
    const asset = assets.find((item) => item.id === id)
    if (!asset) return

    // сразу показываем новое место, не дожидаясь сервера
    setAssets((prev) => prev.map((item) => (item.id === id ? { ...item, x, y } : item)))
    setMoveHistory((prev) => [...prev, { x, y }])
    setError(null)

    const offline = typeof navigator !== 'undefined' && !navigator.onLine
    try {
      if (offline) {
        if (asset.is_mobile) {
          await enqueue('asset_move', {
            assetId: id,
            x,
            y,
            note: 'перетащен на карте (офлайн)',
            client_ts: new Date().toISOString(),
          })
        } else {
          await enqueue('asset_update', {
            assetId: id,
            patch: { x, y },
            base_version: asset.version,
            client_ts: new Date().toISOString(),
          })
        }
        await syncOutbox()
      } else if (asset.is_mobile) {
        await syncApi.move(id, { x, y, note: 'перетащен на карте', source: 'online' })
        await refresh()
      } else {
        await gisApi.update(id, { x, y })
        await refresh()
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось переместить объект')
      await refresh()
    }
  }

  const uploadMap = async () => {
    if (!mapFile) {
      setMapError('Выберите файл изображения')
      return
    }
    setMapSaving(true)
    setMapError(null)
    try {
      const created = await gisApi.uploadMap(mapFile, {
        name: mapForm.name.trim() || 'Новая карта',
        meters_per_pixel: Number(mapForm.mpp.replace(',', '.')) || 0.5,
        origin_x: Number(mapForm.ox.replace(',', '.')) || 0,
        origin_y: Number(mapForm.oy.replace(',', '.')) || 0,
      })
      setLayer(created)
      setMapOpen(false)
      setMapFile(null)
      await refresh()
    } catch (err) {
      setMapError(err instanceof ApiError ? err.message : 'Не удалось загрузить карту')
    } finally {
      setMapSaving(false)
    }
  }

  const submitMove = async () => {
    if (!movingAsset || !moveDraft) return
    setMoveSaving(true)
    setError(null)
    try {
      await enqueue('asset_move', {
        assetId: movingAsset.id,
        x: moveDraft.x,
        y: moveDraft.y,
        note: moveNote.trim() || undefined,
        client_ts: new Date().toISOString(),
      })
      await syncOutbox()
      await refresh()
      setMoveHistory((prev) => [...prev, { x: moveDraft.x, y: moveDraft.y }])
      setMovingAsset(null)
      setMoveDraft(null)
      setMoveNote('')
      setSheetOpen(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить перемещение')
    } finally {
      setMoveSaving(false)
    }
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
    <div
      className="absolute inset-x-0 top-0 overflow-hidden bg-[#070C10]"
      style={{ bottom: 'var(--bottom-nav-bar)' }}
    >
      {view === 'map' ? (
        layer ? (
          <MapView
            layer={layer}
            assets={filtered}
            selectedId={selectedId}
            onSelect={openAsset}
            adding={adding || Boolean(placeAssetId) || Boolean(movingAsset) || vlMode}
            onMapClick={handleMapClick}
            draft={draft ?? moveDraft}
            vlPath={vlPath}
            history={moveHistory}
            draggable={can('asset.create') && !movingAsset && !placeAssetId}
            onDragEnd={(id, x, y) => void handleAssetDrop(id, x, y)}
            links={graph?.edges ?? []}
            positions={Object.fromEntries(
              assets
                .filter((asset) => asset.x !== null && asset.y !== null)
                .map((asset) => [asset.id, [asset.y as number, asset.x as number] as [number, number]]),
            )}
            onLinkClick={openLinkEditor}
            linkMode={linkMode}
            dragFrom={dragFrom}
            onConnectStart={startLinkDrag}
            onConnectDrop={(id) => void dropLinkDrag(id)}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-ink2">
            {loading ? 'Загружаем карту…' : 'Карта недоступна'}
          </div>
        )
      ) : graph ? (
        <Suspense fallback={<div className="flex h-full items-center justify-center text-ink2">Строим схему…</div>}>
          <SchemaView
            graph={graph}
            selectedId={selectedId}
            onSelect={openAsset}
            canEdit={can('settings.edit')}
            canSwitch={canSwitch}
            assetStates={assetStates}
            onGraphChanged={() => void loadGraph()}
          />
        </Suspense>
      ) : (
        <div className="flex h-full items-center justify-center text-ink2">Строим схему…</div>
      )}

      {/* верхняя панель: вид + фильтры. 38a: на телефоне в режиме схемы её нет —
          переключатель Карта/Схема в шапке, а холст занимает всю площадь. */}
      <div
        className={`pointer-events-none absolute inset-x-0 top-0 z-[1000] p-3 ${
          view === 'schema' ? 'hidden md:block' : ''
        }`}
      >
        <div className="pointer-events-auto flex flex-wrap items-center gap-2">
          <div className="flex rounded-full border border-line bg-bg/85 p-1 backdrop-blur">
            <button
              type="button"
              onClick={() => { setView('map'); setSearchParams({}, { replace: true }) }}
              className={`rounded-full px-3 py-1.5 text-[12px] ${view === 'map' ? 'bg-accent text-[#08131F]' : 'text-ink2'}`}
            >
              Карта
            </button>
            <button
              type="button"
              data-tour="schema"
              onClick={() => { setView('schema'); setSearchParams({ view: 'schema' }, { replace: true }) }}
              className={`rounded-full px-3 py-1.5 text-[12px] ${view === 'schema' ? 'bg-accent text-[#08131F]' : 'text-ink2'}`}
            >
              Схема
            </button>
            {can('settings.edit') ? (
              <button
                type="button"
                className="admin-only hidden whitespace-nowrap rounded-full border border-line bg-bg/85 px-3 py-1.5 text-[12px] text-ink2 backdrop-blur hover:text-ink md:inline-flex"
                onClick={() => setMapOpen(true)}
              >
                🖼 Загрузить карту
              </button>
            ) : null}
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

        {movingAsset ? (
          <div className="pointer-events-auto mt-2 flex items-center justify-between gap-3 rounded-xl border border-warm/40 bg-warm/10 px-3 py-2 text-[13px] text-warm backdrop-blur">
            <span>
              {moveDraft
                ? `Перемещение ${movingAsset.code}: X ${moveDraft.x} м, Y ${moveDraft.y} м`
                : `Куда переставить «${movingAsset.code}»? Кликните по карте`}
            </span>
            <button
              type="button"
              className="text-[12px] underline"
              onClick={() => {
                setMovingAsset(null)
                setMoveDraft(null)
              }}
            >
              Отмена
            </button>
          </div>
        ) : null}

        {adding ? (
          <div className="pointer-events-auto mt-2 flex items-center justify-between gap-3 rounded-xl border border-accent/40 bg-accent/10 px-3 py-2 text-[13px] text-accent backdrop-blur">
            <span>
              {draft ? `Точка: X ${draft.x} м, Y ${draft.y} м` : 'Тапните по карте, чтобы поставить объект'}
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
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: powerStateOf(status, false).color }} />
              {powerStateOf(status, false).label}
            </div>
          ))}
          <div className="mt-1 text-ink3">
            <span style={{ color: POWER_COLOR.on }}>●</span> под напряжением ·{' '}
            <span style={{ color: POWER_COLOR.off }}>●</span> обесточено · ⏚ заземлено
          </div>
        </div>
      ) : (
        <div className="pointer-events-none absolute bottom-4 left-3 z-[1000] hidden rounded-xl border border-line bg-bg/85 p-3 text-[11px] backdrop-blur sm:block">
          <div className="mb-1.5 text-ink3">Обозначения</div>
          <div className="text-ink2"><span style={{ color: POWER_COLOR.on }}>━━</span> красная сплошная — под напряжением</div>
          <div className="text-ink2"><span style={{ color: POWER_COLOR.off }}>┅┅</span> зелёная пунктирная — отключено / без питания</div>
          <div className="text-ink2">
            <span style={{ color: POWER_COLOR.on }}>⚡</span> ячейка включена - под напряжением ·{' '}
            <span style={{ color: POWER_COLOR.off }}>○</span> отключена/заземлена - обесточено
          </div>
          <div className="text-ink2"><span className="tracking-[2px]">···</span> точки — перемычка между ячейками</div>
          <div className="text-ink2">→ направление «выход → вход» · ⏚ заземлено</div>
          <div className="text-ink2">фидер — линия от источника к приёмнику</div>
        </div>
      )}

      {error && !connectFrom && !editLink ? (
        <div className="pointer-events-auto fixed left-1/2 top-20 z-[1200] flex w-[min(92vw,420px)] -translate-x-1/2 items-start gap-2 rounded-xl border border-bad/50 bg-[#2A1114]/95 px-3 py-2 text-[12px] text-bad shadow-xl">
          <span className="flex-1">{error}</span>
          <button type="button" onClick={() => setError(null)}>✕</button>
        </div>
      ) : null}

      {editLink ? (
        <div className="absolute inset-x-3 bottom-24 z-[1002] rounded-xl border border-accent/50 bg-surface1 p-3 text-[12px] shadow-xl sm:left-auto sm:right-4 sm:w-[320px]">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-semibold text-ink">Связь</span>
            <button type="button" className="text-ink3" onClick={() => setEditLink(null)}>✕</button>
          </div>
          <label className="mb-2 block text-[11px] text-ink3">
            Тип соединения
            <select className="input mt-1 h-8" value={editLink.type} onChange={(e) => setEditLink({ ...editLink, type: e.target.value })}>
              <option value="cable">Кабель</option>
              <option value="overhead">Воздушная линия</option>
              <option value="busbar">Шина</option>
              <option value="jumper">Перемычка</option>
            </select>
          </label>
          <div className="mb-2 grid grid-cols-2 gap-2">
            <label className="block text-[11px] text-ink3">
              Марка
              <input className="input mt-1 h-8" value={editLink.mark} onChange={(e) => setEditLink({ ...editLink, mark: e.target.value })} placeholder="СБ-3×95" />
            </label>
            <label className="block text-[11px] text-ink3">
              Длина, м
              <input className="input mt-1 h-8" value={editLink.length} inputMode="decimal" onChange={(e) => setEditLink({ ...editLink, length: e.target.value })} placeholder="120" />
            </label>
          </div>
          <div className="mb-2 grid grid-cols-2 gap-2">
            <label className="block text-[11px] text-ink3">
              № кабеля
              <input className="input mt-1 h-8" value={editLink.no} onChange={(e) => setEditLink({ ...editLink, no: e.target.value })} placeholder="КЛ-17" />
            </label>
            <label className="block text-[11px] text-ink3">
              Статус
              <select className="input mt-1 h-8" value={editLink.status} onChange={(e) => setEditLink({ ...editLink, status: e.target.value })}>
                <option value="in_work">в работе</option>
                <option value="reserve">резерв</option>
                <option value="repair">ремонт</option>
                <option value="dismounted">демонтирован</option>
              </select>
            </label>
          </div>
          <label className="mb-2 block text-[11px] text-ink3">
            Установлен на
            <input className="input mt-1 h-8" value={editLink.installed} onChange={(e) => setEditLink({ ...editLink, installed: e.target.value })} placeholder="оп.4" />
          </label>
          <label className="mb-2 block text-[11px] text-ink3">
            Состояние
            <select className="input mt-1 h-8" value={editLink.state} onChange={(e) => setEditLink({ ...editLink, state: e.target.value })}>
              <option value="connected">Включена</option>
              <option value="open">Разомкнута</option>
              <option value="grounded">Заземлена</option>
            </select>
          </label>
          <div className="flex gap-2">
            <button type="button" className="btn-primary h-8 flex-1" disabled={linkSaving} onClick={() => void saveLinkEdit()}>Сохранить</button>
            <button
              type="button"
              className="btn-ghost h-8 text-bad"
              title="Удалить связь"
              aria-label="Удалить связь"
              disabled={linkSaving}
              onClick={() => setConfirmRemoveLink(true)}
            >
              🗑
            </button>
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmRemoveLink}
        title="Удалить связь?"
        message="Связь исчезнет с карты и из схемы. Объекты и их история сохранятся."
        confirmLabel="Удалить"
        busy={linkSaving}
        onConfirm={async () => {
          await removeLink()
          setConfirmRemoveLink(false)
        }}
        onCancel={() => setConfirmRemoveLink(false)}
      />

      {isAdmin && view === 'map' && !adding ? (
        <div className="absolute bottom-5 right-4 z-[1000] flex gap-2">
          <button
            type="button"
            onClick={() => {
              setLinkMode((prev) => !prev)
              setDragFrom(null)
              setConnecting(false)
              setConnectFrom(null)
              setConnectTo(null)
              setError(null)
            }}
            className={`flex h-12 items-center gap-2 rounded-full border px-4 text-[13px] font-semibold ${
              linkMode ? 'border-accent bg-accent text-[#08131F]' : 'border-line bg-bg/90 text-ink'
            }`}
          >
            🔗 Связать
          </button>
          <button
            type="button"
            onClick={() => {
              setAdding(false)
              setLinkMode(false)
              setCompositeDialog(true)
            }}
            className={`flex h-12 items-center gap-2 rounded-full border px-4 text-[13px] font-semibold shadow-lg ${
              compositeMode ? 'border-accent bg-accent/15 text-accent' : 'border-line bg-bg/90 text-ink'
            }`}
          >
            Комплект
          </button>
          <button
            type="button"
            onClick={vlMode ? () => { setVlMode(false); setVlPath([]); setVlDialog(false) } : startVl}
            className={`flex h-12 items-center gap-2 rounded-full border px-4 text-[13px] font-semibold shadow-lg ${
              vlMode ? 'border-warm bg-warm/20 text-warm' : 'border-line bg-bg/90 text-ink'
            }`}
          >
            ВЛ
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
        open={sheetOpen && !draft && !connectAssetId && !moveDraft}
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
            onDeleted={() => {
              setSelectedId(null)
              setSheetOpen(false)
              void refresh()
            }}
            canManage={can('asset.create')}
            canSwitch={canSwitch}
            canManageDocs={canManageDocs}
            onStateChanged={handleStateChanged}
            onMove={
              can('asset.move')
                ? (asset) => {
                    setMovingAsset(asset)
                    setMoveDraft(null)
                    setSheetOpen(false)
                  }
                : undefined
            }
          />
        ) : null}
      </BottomSheet>

      {/* форма перемещения «кукушки» */}
      <BottomSheet
        open={Boolean(moveDraft) && Boolean(movingAsset)}
        onClose={() => {
          setMoveDraft(null)
          setMovingAsset(null)
        }}
        title={movingAsset ? `Перемещение · ${movingAsset.code}` : 'Перемещение'}
      >
        <div className="space-y-3">
          <div className="rounded-xl bg-surface2/60 px-3 py-2 text-[13px]">
            <div className="text-ink3">Новое положение</div>
            <div className="mt-0.5">
              X {moveDraft?.x} м · Y {moveDraft?.y} м
            </div>
          </div>
          <label className="block">
            <span className="label">Куда переставили / причина</span>
            <input
              className="input"
              value={moveNote}
              onChange={(e) => setMoveNote(e.target.value)}
              placeholder="Гор. +85, у водоотлива"
            />
          </label>
          {error ? <Alert kind="error">{error}</Alert> : null}
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-primary flex-1"
              disabled={moveSaving}
              onClick={() => void submitMove()}
            >
              {moveSaving ? 'Сохраняем…' : 'Переместить'}
            </button>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => {
                setMoveDraft(null)
                setMovingAsset(null)
              }}
            >
              Отмена
            </button>
          </div>
          <p className="text-[11px] text-ink3">
            Перемещение сохраняется в истории объекта; без сети уйдёт при появлении связи.
          </p>
        </div>
      </BottomSheet>

      {/* выбор порта при соединении */}
      <BottomSheet
        open={sheetOpen && Boolean(connectAssetId)}
        onClose={() => setSheetOpen(false)}
        title={
          connectChild
            ? `${connectChild.name} · выберите порт ${connectStep === 'from' ? 'OUT' : 'IN'}`
            : connectAsset
              ? `${connectAsset.code} · выберите порт ${connectStep === 'from' ? 'OUT' : 'IN'}`
              : 'Порт'
        }
      >
        <div className="space-y-3">
          {connectChild ? (
            <div className="flex items-center justify-between rounded-lg border border-accent/40 bg-surface2 px-2 py-1 text-[12px]">
              <span>
                Ячейка: <b>{connectChild.name}</b>
              </span>
              <button
                type="button"
                className="btn-ghost h-7 px-2 text-[11px]"
                onClick={() => {
                  if (connectBlockId) void openConnectPicker(connectBlockId)
                }}
              >
                ← к комплексу
              </button>
            </div>
          ) : connectChildren.length > 0 ? (
            <div>
              <div className="mb-1 text-[11px] uppercase tracking-wide text-ink3">
                От какой ячейки комплекса?
              </div>
              <div className="flex flex-wrap gap-1.5">
                {connectChildren.map((child) => (
                  <button
                    key={child.id}
                    type="button"
                    className="rounded-lg border border-line bg-surface2 px-2 py-1 text-[12px] hover:border-accent"
                    onClick={() => pickChildPorts(child)}
                  >
                    {child.name}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
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
      {compositeDialog ? (
        <div className="fixed inset-0 z-[1400] flex items-end justify-center bg-black/60 p-3 sm:items-center">
          <div className="card modal-safe w-full max-w-md p-4 text-[13px]">
            <div className="mb-2 text-[15px] font-semibold">Разместить комплект</div>
            <p className="mb-3 text-[12px] text-ink3">
              Одно оборудование с ячейками: на карте появится один объект, на схеме — рамка
              с ячейками. Состав задаётся в типе (флаг «Комплектное оборудование»).
            </p>
            {types.filter((type) => type.is_composite).length === 0 ? (
              <p className="mb-3 text-[12px] text-warm">
                Нет комплектных типов. Включите флаг в «Типах» и укажите состав.
              </p>
            ) : (
              <label className="mb-3 block text-[11px] text-ink3">
                Тип комплекта
                <select className="input mt-1 h-9" value={compositeTypeId} onChange={(e) => setCompositeTypeId(e.target.value)}>
                  <option value="">— выберите —</option>
                  {types.filter((type) => type.is_composite).map((type) => (
                    <option key={type.id} value={type.id}>{type.name}</option>
                  ))}
                </select>
              </label>
            )}
            <div className="flex gap-2">
              <button
                type="button"
                className="btn-primary h-9 flex-1"
                disabled={!compositeTypeId}
                onClick={() => { setCompositeDialog(false); setCompositeMode(true); setHint('Кликните на карте место для комплекта') }}
              >
                Указать место
              </button>
              <button type="button" className="btn-ghost h-9" onClick={() => setCompositeDialog(false)}>Отмена</button>
            </div>
          </div>
        </div>
      ) : null}

      {vlDialog ? (
        <div className="fixed inset-0 z-[1400] flex items-end justify-center bg-black/60 p-3 sm:items-center">
          <div className="card modal-safe w-full max-w-md p-4 text-[13px]">
            <div className="mb-2 text-[15px] font-semibold">Построить ВЛ</div>
            <p className="mb-3 text-[12px] text-ink3">
              Задайте количество опор и нумерацию, затем поставьте на карте несколько точек —
              линия пойдёт по ним. Enter или кнопка «Завершить» — построить ВЛ.
            </p>
            <div className="mb-2 grid grid-cols-2 gap-2">
              <label className="text-[11px] text-ink3">
                Количество
                <input className="input mt-1 h-9" inputMode="numeric" value={vlForm.count} onChange={(e) => setVlForm({ ...vlForm, count: e.target.value })} />
              </label>
              <label className="text-[11px] text-ink3">
                Начальный номер
                <input className="input mt-1 h-9" inputMode="numeric" value={vlForm.start} onChange={(e) => setVlForm({ ...vlForm, start: e.target.value })} />
              </label>
              <label className="text-[11px] text-ink3">
                Шаг
                <input className="input mt-1 h-9" inputMode="numeric" value={vlForm.step} onChange={(e) => setVlForm({ ...vlForm, step: e.target.value })} />
              </label>
              <label className="text-[11px] text-ink3">
                Префикс
                <input className="input mt-1 h-9" value={vlForm.prefix} onChange={(e) => setVlForm({ ...vlForm, prefix: e.target.value })} />
              </label>
              <label className="text-[11px] text-ink3">
                Откуда (оборудование)
                <select className="input mt-1 h-9" value={vlForm.sourceId} onChange={(e) => setVlForm({ ...vlForm, sourceId: e.target.value })}>
                  <option value="">— не указывать —</option>
                  {assets.map((asset) => (
                    <option key={asset.id} value={asset.id}>{asset.name}</option>
                  ))}
                </select>
              </label>
              <label className="text-[11px] text-ink3">
                Куда (оборудование)
                <select className="input mt-1 h-9" value={vlForm.targetId} onChange={(e) => setVlForm({ ...vlForm, targetId: e.target.value })}>
                  <option value="">— не указывать —</option>
                  {assets.map((asset) => (
                    <option key={asset.id} value={asset.id}>{asset.name}</option>
                  ))}
                </select>
              </label>
            </div>
            <p className="mb-2 text-[11px] text-ink3">
              Если выбраны «Откуда» и «Куда» — можно ничего не кликать, линия пойдёт по прямой,
              опоры встанут равномерно между ними. Клики по карте добавляют изломы трассы.
            </p>
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                className="btn-primary h-10 flex-1"
                onClick={() => {
                  setVlDialog(false)
                  setVlPath([])
                  setHint('Кликайте точки линии на карте. Enter — завершить')
                }}
              >
                Указать точки
              </button>
              <button
                type="button"
                className="btn-ghost h-10"
                onClick={() => { setVlDialog(false); setVlMode(false); setVlPath([]) }}
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {vlMode && !vlDialog ? (
        <div className="fixed inset-x-3 bottom-[calc(150px+env(safe-area-inset-bottom))] z-[1350] flex items-center gap-2 rounded-xl border border-accent/50 bg-surface1 p-2 text-[12px] shadow-xl sm:left-1/2 sm:right-auto sm:w-[380px] sm:-translate-x-1/2">
          <span className="min-w-0 flex-1 text-ink2">Точек: {vlPath.length}</span>
          <button type="button" className="btn-primary h-9 px-3" disabled={vlSaving || (vlPath.length < 2 && !(vlForm.sourceId && vlForm.targetId))} onClick={() => void finishVl()}>
            {vlSaving ? 'Строим…' : 'Завершить'}
          </button>
          <button type="button" className="btn-ghost h-9 px-2" onClick={() => { setVlMode(false); setVlPath([]) }}>
            ✕
          </button>
        </div>
      ) : null}

      {hint ? (
        <div className="fixed inset-x-3 top-16 z-[1350] mx-auto max-w-md rounded-lg border border-accent/40 bg-surface1 px-3 py-2 text-[12px] text-ink2 shadow-lg" onClick={() => setHint(null)}>
          {hint}
        </div>
      ) : null}

      <BottomSheet
        open={placePickerOpen}
        onClose={() => {
          setPlacePickerOpen(false)
          setDraft(null)
        }}
        title={draft ? `Куда поставить? X ${draft.x} м, Y ${draft.y} м` : 'Выбор объекта'}
      >
        <div className="space-y-2">
          <input
            className="input h-10"
            value={placeQuery}
            onChange={(e) => setPlaceQuery(e.target.value)}
            placeholder="Поиск по названию или коду"
          />
          <div className="max-h-[45vh] space-y-1 overflow-y-auto">
            {placePickerItems.map((asset) => (
              <button
                key={asset.id}
                type="button"
                className="flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left hover:bg-surface2"
                disabled={saving}
                onClick={() => void placeExisting(asset.id)}
              >
                <span className="min-w-0">
                  <span className="block truncate text-[13px] text-ink">
                    {asset.type.icon} {asset.name}
                  </span>
                  <span className="block text-[11px] text-ink3">
                    {asset.code} · {asset.type.name}
                  </span>
                </span>
                <span className="shrink-0 text-[11px] text-ink3">
                  {asset.x === null ? 'не размещён' : `X ${asset.x} · Y ${asset.y}`}
                </span>
              </button>
            ))}
            {placePickerItems.length === 0 ? (
              <p className="text-[12px] text-ink3">Ничего не найдено</p>
            ) : null}
          </div>
          <button
            type="button"
            className="btn-ghost h-10 w-full"
            onClick={() => {
              setPlacePickerOpen(false)
              setSheetOpen(true)
            }}
          >
            + Создать новый объект здесь
          </button>
        </div>
      </BottomSheet>

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

      {mapOpen ? (
        <div className="modal-safe fixed inset-0 z-[1450] flex items-end justify-center bg-black/60 sm:items-center sm:p-4">
          <div className="max-h-[calc(100dvh-var(--bottom-nav)-16px)] w-full max-w-lg overflow-y-auto rounded-t-2xl border border-line bg-surface1 p-4 md:max-h-none sm:rounded-2xl">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[16px] font-semibold">Новая подложка карты</h2>
              <button type="button" className="btn-ghost h-9 px-3 text-[12px]" onClick={() => setMapOpen(false)}>
                Закрыть
              </button>
            </div>

            {mapError ? <Alert kind="error">{mapError}</Alert> : null}

            <div className="space-y-3">
              <label className="block">
                <span className="label">Изображение (PNG, JPEG, WebP)</span>
                <input
                  className="input h-10 py-1.5"
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={(e) => setMapFile(e.target.files?.[0] ?? null)}
                />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="label">Название</span>
                  <input
                    className="input h-10"
                    value={mapForm.name}
                    onChange={(e) => setMapForm({ ...mapForm, name: e.target.value })}
                  />
                </label>
                <label className="block">
                  <span className="label">Масштаб, м/пиксель</span>
                  <input
                    className="input h-10"
                    value={mapForm.mpp}
                    onChange={(e) => setMapForm({ ...mapForm, mpp: e.target.value })}
                    placeholder="0.5"
                  />
                </label>
                <label className="block">
                  <span className="label">Начало X, м</span>
                  <input
                    className="input h-10"
                    value={mapForm.ox}
                    onChange={(e) => setMapForm({ ...mapForm, ox: e.target.value })}
                  />
                </label>
                <label className="block">
                  <span className="label">Начало Y, м</span>
                  <input
                    className="input h-10"
                    value={mapForm.oy}
                    onChange={(e) => setMapForm({ ...mapForm, oy: e.target.value })}
                  />
                </label>
              </div>
              <p className="text-[11px] text-ink3">
                Координаты объектов заданы в метрах и не меняются: новая подложка просто
                накладывается на ту же систему координат. Масштаб 0.5 м/px соответствует
                прежней карте.
              </p>
            </div>

            <div className="mt-4 flex gap-2">
              <button
                type="button"
                className="btn-primary px-5"
                disabled={mapSaving || !mapFile}
                onClick={() => void uploadMap()}
              >
                {mapSaving ? 'Загружаем…' : 'Загрузить карту'}
              </button>
              <button type="button" className="btn-ghost" onClick={() => setMapOpen(false)}>
                Отмена
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {can('asset.create') && view === 'map' ? (
        <button
          type="button"
          className="absolute right-3 z-[1002] grid h-14 w-14 place-items-center rounded-2xl bg-accent text-[28px] font-semibold text-[#06111f] shadow-xl active:scale-95 md:hidden"
          style={{ bottom: '236px' }}
          aria-label={adding ? 'Отменить добавление' : 'Добавить объект'}
          onClick={() => (adding ? cancelAdding() : setAdding(true))}
        >
          {adding ? '×' : '+'}
        </button>
      ) : null}

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
