import { useCallback, useEffect, useMemo, useState } from 'react'
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
import { STATUS_COLOR, STATUS_LABEL, gisApi } from '../../lib/gis'
import { ApiError } from '../../lib/api'

const NODE_W = 210
const NODE_H = 84

type AssetNodeData = { node: GraphNode; editable: boolean }

function portLabel(port: AssetPort): string {
  return `${port.code}${port.nominal_voltage_kv ? ` · ${port.nominal_voltage_kv} кВ` : ''}`
}

function AssetNode({ data, selected }: NodeProps<Node<AssetNodeData>>) {
  const { node, editable } = data
  const statusColor = STATUS_COLOR[node.status] ?? '#6B7A8A'
  const dim = !node.energized
  const inputs = node.ports.filter((port) => port.kind === 'in' || port.kind === 'io')
  const outputs = node.ports.filter((port) => port.kind === 'out' || port.kind === 'io')

  const handleStyle = (index: number, total: number): React.CSSProperties => ({
    top: `${((index + 1) / (total + 1)) * 100}%`,
  })

  return (
    <div
      className={`w-[210px] rounded-xl border bg-surface1 px-3 py-2 text-left transition ${
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
          {inputs.map((port, index) => (
            <Handle
              key={port.id}
              id={port.id}
              type="target"
              position={Position.Left}
              style={handleStyle(index, inputs.length)}
              title={portLabel(port)}
              className="!h-3 !w-3 !border-2 !border-accent !bg-surface1"
            />
          ))}
          {outputs.map((port, index) => (
            <Handle
              key={port.id}
              id={port.id}
              type="source"
              position={Position.Right}
              style={handleStyle(index, outputs.length)}
              title={portLabel(port)}
              className="!h-3 !w-3 !border-2 !border-accent !bg-surface1"
            />
          ))}
          {inputs.length === 0 ? (
            <Handle
              type="target"
              position={Position.Left}
              className="!h-2 !w-2 !border-0 !bg-line"
            />
          ) : null}
          {outputs.length === 0 ? (
            <Handle
              type="source"
              position={Position.Right}
              className="!h-2 !w-2 !border-0 !bg-line"
            />
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

  useEffect(() => {
    // при обновлении графа после сохранения режим редактирования не сбрасываем
    setOverrides({})
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
        data: { node, editable: editMode && canEdit },
        selected: node.id === selectedId,
        draggable: editMode && canEdit,
      })),
    [graph.nodes, positions, selectedId, editMode, canEdit],
  )

  const edges = useMemo(() => buildEdges(graph), [graph])

  const save = useCallback(
    async (items: Array<{ asset_id: string; x: number; y: number }>, message: string) => {
      setSaving(true)
      setError(null)
      try {
        const result = await gisApi.saveSchemaLayout(items)
        setStatus(`${message}: сохранено узлов ${result.updated}`)
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
              <span className="hidden text-[11px] text-ink3 sm:inline">порты: потяните от кружка к кружку</span>
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
        nodesConnectable={editMode && canEdit}
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
