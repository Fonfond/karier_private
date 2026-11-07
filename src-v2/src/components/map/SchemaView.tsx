import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
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
const GRID = 20

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
  return {
    x: Math.min(1, Math.max(0, 0.5 + dx * t)),
    y: Math.min(1, Math.max(0, 0.5 + dy * t)),
  }
}

/** Позиции всех портов узла: сохранённые в БД или рассчитанные по умолчанию. */
export function portsForNode(node: GraphNode): Record<string, XYPosition> {
  const result: Record<string, XYPosition> = {}
  const groups: Record<string, AssetPort[]> = {}
  node.ports.forEach((port) => {
    ;(groups[port.kind] ||= []).push(port)
  })
  node.ports.forEach((port) => {
    if (port.schema_x != null && port.schema_y != null) {
      result[port.id] = { x: port.schema_x, y: port.schema_y }
      return
    }
    const siblings = groups[port.kind] ?? [port]
    const index = siblings.findIndex((item) => item.id === port.id)
    result[port.id] = defaultPortPosition(port, Math.max(index, 0), siblings.length)
  })
  return result
}

function AssetNode({ data, selected }: NodeProps<Node<AssetNodeData>>) {
  const { node, editable, portDrag, portPositions, onPortMove } = data
  const statusColor = STATUS_COLOR[node.status] ?? '#6B7A8A'
  const dim = !node.energized
  const box = useRef<HTMLDivElement | null>(null)
  const dragging = useRef<string | null>(null)

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
    const point = clampToPerimeter(
      (event.clientX - rect.left) / rect.width,
      (event.clientY - rect.top) / rect.height,
    )
    onPortMove(dragging.current, point.x, point.y)
  }

  const stopPortDrag = (event: React.PointerEvent) => {
    if (!dragging.current) return
    ;(event.target as HTMLElement).releasePointerCapture?.(event.pointerId)
    dragging.current = null
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

      {node.ports.map((port) => {
        const position = portPositions[port.id] ?? { x: 0.5, y: 0.5 }
        const interactive = editable && !portDrag
        return (
          <Handle
            key={port.id}
            id={port.id}
            type={port.kind === 'out' ? 'source' : 'target'}
            position={sideOf(position)}
            title={portLabel(port)}
            isConnectable={interactive}
            style={{
              left: `${position.x * 100}%`,
              top: `${position.y * 100}%`,
              // в режиме портов handle не соединяет, но должен ловить перетаскивание
              pointerEvents: portDrag ? 'auto' : undefined,
            }}
            className={`!h-3 !w-3 !border-2 ${
              portDrag
                ? '!border-warm !bg-warm/40 cursor-grab'
                : editable
                  ? '!border-accent !bg-surface1'
                  : '!border-accent/70 !bg-surface1 !h-2 !w-2'
            }`}
            onPointerDown={(event) => startPortDrag(port, event)}
            onPointerMove={movePort}
            onPointerUp={stopPortDrag}
          />
        )
      })}

      {node.ports.length === 0 ? (
        <>
          <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-line" />
          <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-line" />
        </>
      ) : null}
    </div>
  )
}

const nodeTypes = { asset: AssetNode }

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
      x: Math.round(((point?.x ?? 0) - NODE_W / 2) / GRID) * GRID,
      y: Math.round(((point?.y ?? 0) - NODE_H / 2) / GRID) * GRID,
    }
  })
  return result
}

/** Позиции узлов: сохранённые в БД, иначе — авто-раскладка. */
function nodePositions(graph: TopologyGraph): Record<string, XYPosition> {
  const auto = dagrePositions(graph)
  const result: Record<string, XYPosition> = {}
  graph.nodes.forEach((node) => {
    result[node.id] =
      node.schema_x != null && node.schema_y != null
        ? { x: node.schema_x, y: node.schema_y }
        : auto[node.id] ?? { x: 0, y: 0 }
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

interface EdgeDraft {
  id: string
  label: string
  cable_mark: string
  length_m: string
  state: string
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
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<AssetNodeData>>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [editMode, setEditMode] = useState(false)
  const [, setDirty] = useState(false)
  const [portDrag, setPortDrag] = useState(false)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<Connection | null>(null)
  const [cableMark, setCableMark] = useState('')
  const [linkType, setLinkType] = useState('cable')
  const [edgeDraft, setEdgeDraft] = useState<EdgeDraft | null>(null)

  /** Перетаскивание порта обновляет только свой узел — остальные не перерисовываются. */
  const onPortMove = useCallback((nodeId: string, portId: string, x: number, y: number) => {
    setNodes((current) =>
      current.map((item) => {
        if (item.id !== nodeId) return item
        return {
          ...item,
          data: {
            ...item.data,
            portPositions: {
              ...item.data.portPositions,
              [portId]: { x: Math.round(x * 40) / 40, y: Math.round(y * 40) / 40 },
            },
          },
        }
      }),
    )
    setDirty(true)
  }, [setNodes])

  // Полная сборка схемы только при смене графа: позиции из БД приоритетнее dagre
  useEffect(() => {
    const positions = nodePositions(graph)
    setNodes(
      graph.nodes.map((node) => ({
        id: node.id,
        type: 'asset',
        position: positions[node.id],
        selected: node.id === selectedId,
        draggable: false,
        data: {
          node,
          editable: false,
          portDrag: false,
          portPositions: portsForNode(node),
          onPortMove: (portId, x, y) => onPortMove(node.id, portId, x, y),
        },
      })),
    )
    setEdges(buildEdges(graph))
    setDirty(false)
    setStatus(null)
    setError(null)
    setEdgeDraft(null)
    setPending(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, setNodes, setEdges])

  // Переключатели режимов меняют только флаги, не трогая позиции
  useEffect(() => {
    setNodes((current) =>
      current.map((item) => ({
        ...item,
        selected: item.id === selectedId,
        draggable: editMode && canEdit && !portDrag,
        data: {
          ...item.data,
          editable: editMode && canEdit,
          portDrag: editMode && canEdit && portDrag,
          onPortMove: (portId: string, x: number, y: number) =>
            onPortMove(item.id, portId, x, y),
        },
      })),
    )
  }, [editMode, canEdit, portDrag, selectedId, onPortMove, setNodes])

  useEffect(() => {
    const timer = setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 60)
    return () => clearTimeout(timer)
  }, [graph, fitView])

  const saveCurrent = async () => {
    setSaving(true)
    setError(null)
    try {
      const items = nodes.map((node) => ({
        asset_id: node.id,
        x: Math.round(node.position.x),
        y: Math.round(node.position.y),
      }))
      const ports = nodes.flatMap((node) =>
        node.data.node.ports.map((port) => {
          const point = node.data.portPositions[port.id]
          return {
            port_id: port.id,
            x: Math.round((point?.x ?? 0.5) * 1000) / 1000,
            y: Math.round((point?.y ?? 0.5) * 1000) / 1000,
          }
        }),
      )
      const result = await gisApi.saveSchemaLayout(items, ports)
      setStatus(`Сохранено: узлов ${result.updated}, портов ${result.updated_ports}`)
      setDirty(false)
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить раскладку')
    } finally {
      setSaving(false)
    }
  }

  const applyAuto = () => {
    const auto = dagrePositions(graph)
    setNodes((current) =>
      current.map((node) => ({ ...node, position: auto[node.id] ?? node.position })),
    )
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

  const openEdge = (_event: React.MouseEvent, edge: Edge) => {
    if (!canEdit) return
    const source = graph.edges.find((item) => item.id === edge.id)
    if (!source) return
    setEdgeDraft({
      id: source.id,
      label: source.label,
      cable_mark: source.cable_mark ?? '',
      length_m: source.length_m != null ? String(source.length_m) : '',
      state: source.state,
    })
  }

  const saveEdge = async () => {
    if (!edgeDraft) return
    setSaving(true)
    setError(null)
    try {
      await gisApi.updateLink(edgeDraft.id, {
        cable_mark: edgeDraft.cable_mark.trim() || null,
        length_m: edgeDraft.length_m ? Number(edgeDraft.length_m.replace(',', '.')) : null,
        state: edgeDraft.state,
      })
      setEdgeDraft(null)
      setStatus('Связь обновлена')
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось изменить связь')
    } finally {
      setSaving(false)
    }
  }

  const removeEdge = async () => {
    if (!edgeDraft) return
    if (!window.confirm('Удалить связь? Объекты и их история останутся.')) return
    setSaving(true)
    try {
      await gisApi.deleteLink(edgeDraft.id)
      setEdgeDraft(null)
      setStatus('Связь удалена')
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось удалить связь')
    } finally {
      setSaving(false)
    }
  }

  const portPositionsForDxf = useMemo(() => {
    const result: Record<string, XYPosition> = {}
    nodes.forEach((node) => {
      Object.assign(result, node.data.portPositions)
    })
    return result
  }, [nodes])

  const positionsForDxf = useMemo(() => {
    const result: Record<string, XYPosition> = {}
    nodes.forEach((node) => {
      result[node.id] = node.position
    })
    return result
  }, [nodes])

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
              <button type="button" className="btn-primary h-8 px-3" disabled={saving} onClick={() => void saveCurrent()}>
                {saving ? 'Сохраняем…' : 'Сохранить раскладку'}
              </button>
              <button type="button" className="btn-ghost h-8 px-3" onClick={applyAuto}>
                Авто-раскладка
              </button>
              <button
                type="button"
                className="btn-ghost h-8 px-3"
                title="Скачать раскладку в DXF для nanoCAD/AutoCAD"
                onClick={() =>
                  downloadDxf(graph, positionsForDxf, portPositionsForDxf, NODE_W, NODE_H)
                }
              >
                ⬇ DXF
              </button>
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={portDrag} onChange={(e) => setPortDrag(e.target.checked)} />
                Двигать порты
              </label>
              <span className="hidden text-[11px] text-ink3 sm:inline">
                {portDrag ? 'тяните кружки по краю узла' : 'клик по связи — редактирование'}
              </span>
            </>
          ) : (
            <span className="hidden text-[11px] text-ink3 sm:inline">
              включите, чтобы двигать узлы, порты и соединять связи
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
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => onSelect(node.id)}
        onEdgeClick={openEdge}
        onNodeDragStop={() => setDirty(true)}
        onConnect={(connection) => {
          if (!editMode || portDrag) return
          if (!connection.sourceHandle || !connection.targetHandle) return
          if (connection.source === connection.target) return
          setPending(connection)
          setStatus(null)
          setError(null)
        }}
        nodesDraggable={editMode && canEdit && !portDrag}
        nodesConnectable={editMode && canEdit && !portDrag}
        snapToGrid
        snapGrid={[GRID, GRID]}
        elementsSelectable
        fitView
        minZoom={0.15}
        maxZoom={1.8}
        proOptions={{ hideAttribution: true }}
        className="bg-[#070C10]"
      >
        <Background color="#1B2733" gap={GRID} size={1} />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>

      {pending ? (
        <div className="absolute inset-x-2 bottom-16 z-20 rounded-xl border border-accent/50 bg-surface1 p-3 text-[12px] shadow-lg sm:left-auto sm:right-2 sm:w-[340px]">
          <div className="mb-2 font-semibold">Новая связь</div>
          <label className="mb-2 block">
            <span className="label">Марка кабеля</span>
            <input className="input h-9" value={cableMark} onChange={(e) => setCableMark(e.target.value)} placeholder="АВБбШв 4×25" />
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
              Соединить
            </button>
            <button type="button" className="btn-ghost h-9 px-3" onClick={() => setPending(null)}>
              Отмена
            </button>
          </div>
        </div>
      ) : null}

      {edgeDraft ? (
        <div className="absolute inset-x-2 bottom-16 z-20 rounded-xl border border-accent/50 bg-surface1 p-3 text-[12px] shadow-lg sm:left-auto sm:right-2 sm:w-[320px]">
          <div className="mb-2 font-semibold">Связь · {edgeDraft.label}</div>
          <label className="mb-2 block">
            <span className="label">Марка кабеля</span>
            <input
              className="input h-9"
              value={edgeDraft.cable_mark}
              onChange={(e) => setEdgeDraft({ ...edgeDraft, cable_mark: e.target.value })}
            />
          </label>
          <div className="mb-2 grid grid-cols-2 gap-2">
            <label className="block">
              <span className="label">Длина, м</span>
              <input
                className="input h-9"
                value={edgeDraft.length_m}
                onChange={(e) => setEdgeDraft({ ...edgeDraft, length_m: e.target.value })}
              />
            </label>
            <label className="block">
              <span className="label">Состояние</span>
              <select
                className="input h-9"
                value={edgeDraft.state}
                onChange={(e) => setEdgeDraft({ ...edgeDraft, state: e.target.value })}
              >
                <option value="connected">включена</option>
                <option value="open">разомкнута</option>
                <option value="grounded">заземлена</option>
              </select>
            </label>
          </div>
          <div className="flex gap-2">
            <button type="button" className="btn-primary h-9 flex-1 px-3" disabled={saving} onClick={() => void saveEdge()}>
              Сохранить
            </button>
            <button type="button" className="btn-danger h-9 px-3" disabled={saving} onClick={() => void removeEdge()}>
              Удалить
            </button>
            <button type="button" className="btn-ghost h-9 px-3" onClick={() => setEdgeDraft(null)}>
              ✕
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
