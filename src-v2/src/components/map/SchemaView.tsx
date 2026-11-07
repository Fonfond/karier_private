import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type XYPosition,
} from '@xyflow/react'
import dagre from 'dagre'
import '@xyflow/react/dist/style.css'
import type { AssetPort, GraphNode, TopologyGraph } from '../../lib/gis'
import { downloadDxf } from '../../lib/dxf'
import { STATUS_COLOR, STATUS_LABEL, gisApi } from '../../lib/gis'
import { ApiError } from '../../lib/api'

const NODE_W = 210
const NODE_H = 84

type AssetNodeData = {
  node: GraphNode
  editable: boolean
  portDrag: boolean
  portPositions: Record<string, XYPosition>
  onPortMove: (portId: string, x: number, y: number) => void
}

function portLabel(port: AssetPort): string {
  return `${port.code}${port.nominal_voltage_kv ? ` · ${port.nominal_voltage_kv} кВ` : ''}`
}

/** Положение порта по умолчанию: вводы слева, отходящие справа, io — снизу. */
export function defaultPortPosition(port: AssetPort, index: number, total: number): XYPosition {
  const step = (index + 1) / (total + 1)
  if (port.kind === 'in') return { x: 0, y: step }
  if (port.kind === 'out') return { x: 1, y: step }
  return { x: step, y: 1 }
}

/** Сторона узла, ближайшая к точке — от неё зависит направление стрелки связи. */
function sideOf(position: XYPosition): Position {
  const distances: Array<[Position, number]> = [
    [Position.Left, position.x],
    [Position.Right, 1 - position.x],
    [Position.Top, position.y],
    [Position.Bottom, 1 - position.y],
  ]
  distances.sort((a, b) => a[1] - b[1])
  return distances[0][0]
}

/** Спроецировать точку на периметр прямоугольника узла (доли 0…1). */
function clampToPerimeter(x: number, y: number): XYPosition {
  const dx = x - 0.5
  const dy = y - 0.5
  if (dx === 0 && dy === 0) return { x: 0.5, y: 1 }
  const tx = dx === 0 ? Number.POSITIVE_INFINITY : 0.5 / Math.abs(dx)
  const ty = dy === 0 ? Number.POSITIVE_INFINITY : 0.5 / Math.abs(dy)
  const t = Math.min(tx, ty, 1)
  const px = Math.min(1, Math.max(0, 0.5 + dx * Math.min(1, t)))
  const py = Math.min(1, Math.max(0, 0.5 + dy * Math.min(1, t)))
  return { x: px, y: py }
}

function AssetNode({ data, selected }: NodeProps<Node<AssetNodeData>>) {
  const { node, editable, portDrag, portPositions, onPortMove } = data
  const statusColor = STATUS_COLOR[node.status] ?? '#6B7A8A'
  const dim = !node.energized
  const box = useRef<HTMLDivElement | null>(null)
  const dragging = useRef<string | null>(null)

  const positionOf = (port: AssetPort, index: number, total: number): XYPosition =>
    portPositions[port.id] ?? defaultPortPosition(port, index, total)

  const startPortDrag = (port: AssetPort, event: React.PointerEvent) => {
    if (!portDrag) return
    event.stopPropagation()
    event.preventDefault()
    dragging.current = port.id
    ;(event.target as HTMLElement).setPointerCapture?.(event.pointerId)
  }

  const movePort = (event: React.PointerEvent) => {
    if (!dragging.current || !box.current) return
    const rect = box.current.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const raw = {
      x: (event.clientX - rect.left) / rect.width,
      y: (event.clientY - rect.top) / rect.height,
    }
    const point = clampToPerimeter(raw.x, raw.y)
    onPortMove(dragging.current, point.x, point.y)
  }

  const stopPortDrag = (event: React.PointerEvent) => {
    if (!dragging.current) return
    ;(event.target as HTMLElement).releasePointerCapture?.(event.pointerId)
    dragging.current = null
  }

  const renderPort = (port: AssetPort, index: number, total: number) => {
    const position = positionOf(port, index, total)
    return (
      <Handle
        key={port.id}
        id={port.id}
        type={port.kind === 'out' ? 'source' : 'target'}
        position={sideOf(position)}
        title={portLabel(port)}
        style={{ left: `${position.x * 100}%`, top: `${position.y * 100}%` }}
        className={`!h-3 !w-3 !border-2 ${
          portDrag ? '!border-warm !bg-warm/40 cursor-grab' : '!border-accent !bg-surface1'
        }`}
        onPointerDown={(event) => startPortDrag(port, event)}
        onPointerMove={movePort}
        onPointerUp={stopPortDrag}
      />
    )
  }

  return (
    <div
      ref={box}
      className={`relative w-[210px] rounded-xl border bg-surface1 px-3 py-2 text-left transition ${
        selected ? 'ring-2 ring-accent' : ''
      } ${node.grounded ? 'border-ground' : 'border-line'} ${dim ? 'opacity-70' : ''}`}
    >
      <div className="flex items-center gap-2">
        <span
          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-sm"
          style={{ background: `${node.type_color ?? '#4C9AFF'}22` }}
        >
          {node.type_icon ?? '●'}
        </span>
        <div className="min-w-0">
          <div className="truncate text-[12px] font-semibold text-ink">{node.code}</div>
          <div className="truncate text-[10px] text-ink3">{node.type_name}</div>
        </div>
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-[10px]">
        <span style={{ color: statusColor }}>●</span>
        <span className="text-ink2">{STATUS_LABEL[node.status] ?? node.status}</span>
        {node.grounded ? <span className="text-ground">⏚</span> : null}
        {node.is_source ? <span className="ml-auto text-warm">источник</span> : null}
      </div>

      {editable ? (
        <>
          {node.ports.map((port) => {
            // каждый порт рисуется ровно один раз, иначе React Flow получает дубли handle id
            const siblings = node.ports.filter((item) => item.kind === port.kind)
            const index = siblings.findIndex((item) => item.id === port.id)
            return renderPort(port, Math.max(index, 0), siblings.length)
          })}
          {node.ports.length === 0 ? (
            <>
              <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-line" />
              <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-line" />
            </>
          ) : null}
        </>
      ) : (
        <>
          <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-line" />
          <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-line" />
        </>
      )}
    </div>
  )
}

const nodeTypes = { asset: AssetNode }

/** Позиции всех портов: сохранённые, локальные сдвиги или значения по умолчанию. */
function buildPortPositions(
  graph: TopologyGraph,
  overrides: Record<string, XYPosition>,
): Record<string, XYPosition> {
  const result: Record<string, XYPosition> = {}
  graph.nodes.forEach((node) => {
    const groups: Record<string, AssetPort[]> = {}
    node.ports.forEach((port) => {
      ;(groups[port.kind] ||= []).push(port)
    })
    node.ports.forEach((port) => {
      if (overrides[port.id]) {
        result[port.id] = overrides[port.id]
        return
      }
      if (port.schema_x != null && port.schema_y != null) {
        result[port.id] = { x: port.schema_x, y: port.schema_y }
        return
      }
      const siblings = groups[port.kind] ?? [port]
      const index = siblings.findIndex((item) => item.id === port.id)
      result[port.id] = defaultPortPosition(port, Math.max(index, 0), siblings.length)
    })
  })
  return result
}

function dagrePositions(graph: TopologyGraph): Record<string, XYPosition> {
  const layout = new dagre.graphlib.Graph()
  layout.setDefaultEdgeLabel(() => ({}))
  layout.setGraph({ rankdir: 'TB', nodesep: 48, ranksep: 90, marginx: 24, marginy: 24 })

  graph.nodes.forEach((node) => layout.setNode(node.id, { width: NODE_W, height: NODE_H }))
  graph.edges.forEach((edge) => {
    if (layout.hasNode(edge.from_asset_id) && layout.hasNode(edge.to_asset_id)) {
      layout.setEdge(edge.from_asset_id, edge.to_asset_id)
    }
  })
  dagre.layout(layout)

  const result: Record<string, XYPosition> = {}
  graph.nodes.forEach((node) => {
    const point = layout.node(node.id)
    result[node.id] = {
      x: (point?.x ?? 0) - NODE_W / 2,
      y: (point?.y ?? 0) - NODE_H / 2,
    }
  })
  return result
}

function buildEdges(graph: TopologyGraph): Edge[] {
  return graph.edges.map((edge) => {
    const open = edge.state !== 'connected'
    const jumper = edge.link_type === 'jumper'
    return {
      id: edge.id,
      source: edge.from_asset_id,
      target: edge.to_asset_id,
      label: edge.label,
      animated: false,
      style: {
        stroke: open ? '#6B7A8A' : jumper ? '#A56BFF' : '#4C9AFF',
        strokeWidth: open ? 1.2 : 1.8,
        strokeDasharray: open ? '6 4' : undefined,
      },
      labelStyle: { fill: '#9FB0C0', fontSize: 10 },
      labelBgStyle: { fill: '#0B1014', fillOpacity: 0.85 },
      labelBgPadding: [4, 2] as [number, number],
      labelBgBorderRadius: 4,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 14,
        height: 14,
        color: open ? '#6B7A8A' : '#4C9AFF',
      },
    }
  })
}

function Flow({
  graph,
  selectedId,
  onSelect,
  canEdit,
  onGraphChanged,
}: {
  graph: TopologyGraph
  selectedId: string | null
  onSelect: (id: string) => void
  canEdit: boolean
  onGraphChanged: () => void
}) {
  const { fitView } = useReactFlow()
  const [editMode, setEditMode] = useState(false)
  const [overrides, setOverrides] = useState<Record<string, XYPosition>>({})
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<Connection | null>(null)
  const [cableMark, setCableMark] = useState('')
  const [linkType, setLinkType] = useState('cable')
  const [portOverrides, setPortOverrides] = useState<Record<string, XYPosition>>({})
  const [portDrag, setPortDrag] = useState(false)

  const auto = useMemo(() => dagrePositions(graph), [graph])

  const base = useMemo(() => {
    const result: Record<string, XYPosition> = {}
    graph.nodes.forEach((node) => {
      if (node.schema_x !== null && node.schema_y !== null) {
        result[node.id] = { x: node.schema_x, y: node.schema_y }
      } else {
        result[node.id] = auto[node.id] ?? { x: 0, y: 0 }
      }
    })
    return result
  }, [graph, auto])

  const positions = useMemo(() => ({ ...base, ...overrides }), [base, overrides])
  const portPositions = useMemo(
    () => buildPortPositions(graph, portOverrides),
    [graph, portOverrides],
  )

  const movePort = useCallback((portId: string, x: number, y: number) => {
    setPortOverrides((prev) => ({
      ...prev,
      [portId]: { x: Math.round(x * 20) / 20, y: Math.round(y * 20) / 20 },
    }))
    setDirty(true)
  }, [])

  useEffect(() => {
    // при обновлении графа после сохранения режим редактирования не сбрасываем
    setOverrides({})
    setPortOverrides({})
    setDirty(false)
    setStatus(null)
    setError(null)
  }, [graph])

  useEffect(() => {
    const timer = setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 60)
    return () => clearTimeout(timer)
  }, [graph, fitView])

  const nodes: Node<AssetNodeData>[] = useMemo(
    () =>
      graph.nodes.map((node) => ({
        id: node.id,
        type: 'asset',
        position: positions[node.id] ?? { x: 0, y: 0 },
        data: {
          node,
          editable: editMode && canEdit,
          portDrag: editMode && canEdit && portDrag,
          portPositions,
          onPortMove: movePort,
        },
        selected: node.id === selectedId,
        draggable: editMode && canEdit && !portDrag,
      })),
    [graph.nodes, positions, selectedId, editMode, canEdit, portDrag, portPositions, movePort],
  )

  const edges = useMemo(() => buildEdges(graph), [graph])

  const save = useCallback(
    async (
      items: Array<{ asset_id: string; x: number; y: number }>,
      ports: Array<{ port_id: string; x: number; y: number }>,
      message: string,
    ) => {
      setSaving(true)
      setError(null)
      try {
        const result = await gisApi.saveSchemaLayout(items, ports)
        setStatus(
          `${message}: узлов ${result.updated}, портов ${result.updated_ports}`,
        )
        setDirty(false)
        onGraphChanged()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось сохранить раскладку')
      } finally {
        setSaving(false)
      }
    },
    [onGraphChanged],
  )

  const saveCurrent = () =>
    void save(
      graph.nodes.map((node) => ({
        asset_id: node.id,
        x: Math.round((positions[node.id]?.x ?? 0) * 10) / 10,
        y: Math.round((positions[node.id]?.y ?? 0) * 10) / 10,
      })),
      Object.entries(portPositions).map(([portId, point]) => ({
        port_id: portId,
        x: Math.round(point.x * 1000) / 1000,
        y: Math.round(point.y * 1000) / 1000,
      })),
      'Ручная раскладка',
    )

  const applyAuto = () => {
    setOverrides(auto)
    setDirty(true)
    setStatus('Авто-раскладка применена — нажмите «Сохранить раскладку»')
  }

  const connect = async () => {
    if (!pending?.sourceHandle || !pending?.targetHandle) return
    setSaving(true)
    setError(null)
    try {
      await gisApi.createLink({
        from_port_id: pending.sourceHandle,
        to_port_id: pending.targetHandle,
        link_type: linkType,
        cable_mark: cableMark.trim() || undefined,
      })
      setStatus('Связь создана')
      setPending(null)
      setCableMark('')
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать связь')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="relative h-full w-full">
      {canEdit ? (
        <div className="pointer-events-auto absolute bottom-3 left-1/2 z-10 flex max-w-[calc(100%-24px)] -translate-x-1/2 flex-wrap items-center justify-center gap-2 rounded-xl border border-line bg-surface1/95 px-2 py-1.5 text-[12px] backdrop-blur">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={editMode} onChange={(e) => setEditMode(e.target.checked)} />
            Режим редактирования
          </label>
          {editMode ? (
            <>
              <button type="button" className="btn-primary h-8 px-3" disabled={saving || !dirty} onClick={saveCurrent}>
                {saving ? 'Сохраняем…' : 'Сохранить раскладку'}
              </button>
              <button type="button" className="btn-ghost h-8 px-3" onClick={applyAuto}>
                Авто-раскладка
              </button>
              <button
                type="button"
                className="btn-ghost h-8 px-3"
                title="Скачать раскладку в DXF для nanoCAD/AutoCAD"
                onClick={() => downloadDxf(graph, positions, portPositions)}
              >
                ⬇ DXF
              </button>
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={portDrag} onChange={(e) => setPortDrag(e.target.checked)} />
                Двигать порты
              </label>
              <span className="hidden text-[11px] text-ink3 sm:inline">
                {portDrag ? 'тяните кружки по краю узла' : 'порты: потяните от кружка к кружку'}
              </span>
            </>
          ) : (
            <span className="hidden text-[11px] text-ink3 sm:inline">
              включите, чтобы двигать узлы и соединять порты
            </span>
          )}
        </div>
      ) : null}

      {error ? (
        <div className="absolute right-2 top-2 z-10 max-w-[320px] rounded-lg border border-bad/40 bg-bad/10 px-3 py-2 text-[12px] text-bad">
          {error}
        </div>
      ) : status ? (
        <div className="absolute right-2 top-2 z-10 max-w-[320px] rounded-lg border border-ok/40 bg-ok/10 px-3 py-2 text-[12px] text-ok">
          {status}
        </div>
      ) : null}

      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelect(node.id)}
        onNodeDragStop={(_, node) => {
          setOverrides((prev) => ({ ...prev, [node.id]: node.position }))
          setDirty(true)
        }}
        onConnect={(connection) => {
          if (!editMode) return
          if (!connection.sourceHandle || !connection.targetHandle) return
          if (connection.source === connection.target) return
          setPending(connection)
          setStatus(null)
          setError(null)
        }}
        nodesDraggable={editMode && canEdit}
        nodesConnectable={editMode && canEdit && !portDrag}
        snapToGrid
        snapGrid={[20, 20]}
        elementsSelectable
        fitView
        minZoom={0.15}
        maxZoom={1.8}
        proOptions={{ hideAttribution: true }}
        className="bg-[#070C10]"
      >
        <Background color="#1B2733" gap={24} size={1} />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>

      {pending ? (
        <div className="absolute inset-x-2 bottom-2 z-20 rounded-xl border border-accent/50 bg-surface1 p-3 text-[12px] shadow-lg sm:left-auto sm:right-2 sm:w-[340px]">
          <div className="mb-2 font-semibold">Новая связь</div>
          <div className="mb-2 text-ink3">
            {pending.sourceHandle?.slice(0, 8)} → {pending.targetHandle?.slice(0, 8)}
          </div>
          <label className="mb-2 block">
            <span className="label">Марка кабеля</span>
            <input
              className="input h-9"
              value={cableMark}
              onChange={(e) => setCableMark(e.target.value)}
              placeholder="АВБбШв 4×25"
            />
          </label>
          <label className="mb-2 block">
            <span className="label">Тип связи</span>
            <select className="input h-9" value={linkType} onChange={(e) => setLinkType(e.target.value)}>
              <option value="cable">Кабель</option>
              <option value="overhead">ВЛ</option>
              <option value="jumper">Перемычка</option>
            </select>
          </label>
          <div className="flex gap-2">
            <button type="button" className="btn-primary h-9 flex-1 px-3" disabled={saving} onClick={() => void connect()}>
              {saving ? 'Создаём…' : 'Соединить'}
            </button>
            <button type="button" className="btn-ghost h-9 px-3" onClick={() => setPending(null)}>
              Отмена
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export function SchemaView({
  graph,
  selectedId,
  onSelect,
  canEdit = false,
  onGraphChanged,
}: {
  graph: TopologyGraph
  selectedId: string | null
  onSelect: (id: string) => void
  canEdit?: boolean
  onGraphChanged?: () => void
}) {
  return (
    <ReactFlowProvider>
      <div className="h-full w-full">
        <Flow
          graph={graph}
          selectedId={selectedId}
          onSelect={onSelect}
          canEdit={canEdit}
          onGraphChanged={onGraphChanged ?? (() => undefined)}
        />
      </div>
    </ReactFlowProvider>
  )
}
