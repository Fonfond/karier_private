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
import { GostSymbol, SchemaFrameOverlay } from './GostSymbols'
import type { SchemaBlock, SchemaFrame, GraphBlock } from '../../lib/gis'
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
  block?: GraphBlock
  onSelectChild?: (id: string) => void
  onAddCell?: (assetId: string) => void
  onDeleteCell?: (assetId: string, cellId: string, name: string) => void
  onToggleCollapse?: (assetId: string, collapsed: boolean) => void
  jumperMode?: boolean
  jumperFirstId?: string | null
  onCellPick?: (blockId: string, cellId: string, name: string) => void
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

  if (data.block) {
    const block = data.block
    const busbars = block.children.filter((child) => child.role === 'busbar')
    const cells = block.children.filter((child) => child.role !== 'busbar')
    const roleColor = (role: string | null) => {
      if (role === 'incoming') return 'border-warm/50 text-warm'
      if (role === 'outgoing') return 'border-accent/50 text-accent'
      if (role === 'section') return 'border-[#C4A1FF]/50 text-[#C4A1FF]'
      return 'border-line text-ink2'
    }

    if (block.collapsed) {
      return (
        <div
          className={`relative w-[188px] rounded-xl border-2 border-accent/50 bg-surface1/95 p-2 ${
            selected ? 'ring-2 ring-accent' : ''
          }`}
        >
          <div className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent/15 text-[13px]">▣</span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[12px] font-semibold text-ink">{block.name}</div>
              <div className="text-[10px] text-ink3">{cells.length + busbars.length} эл. · {block.code}</div>
            </div>
            <button
              type="button"
              className="btn-ghost h-6 px-1.5 text-[11px]"
              title="Развернуть блок"
              onClick={(event) => {
                event.stopPropagation()
                data.onToggleCollapse?.(block.asset_id, false)
              }}
            >
              ▸
            </button>
          </div>
          <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-accent" />
          <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-accent" />
        </div>
      )
    }

    return (
      <div
        className={`relative w-[320px] max-w-[calc(100vw-28px)] rounded-xl border-2 border-accent/45 bg-surface1/95 ${
          selected ? 'ring-2 ring-accent' : ''
        }`}
      >
        <div className="flex items-start justify-between gap-2 border-b border-line px-2.5 py-2">
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold leading-tight text-ink">{block.name}</div>
            <div className="mt-0.5 text-[10px] text-ink3">
              {block.code} · {cells.length} ячеек · {busbars.length} секции
            </div>
          </div>
          <div className="flex items-center gap-1">
            {data.editable && data.onAddCell ? (
              <button
                type="button"
                className="btn-ghost h-6 px-1.5 text-[11px]"
                title="Добавить ячейку"
                onClick={(event) => {
                  event.stopPropagation()
                  data.onAddCell?.(block.asset_id)
                }}
              >
                ＋
              </button>
            ) : null}
            <button
              type="button"
              className="btn-ghost h-6 px-1.5 text-[11px]"
              title="Свернуть блок"
              onClick={(event) => {
                event.stopPropagation()
                data.onToggleCollapse?.(block.asset_id, true)
              }}
            >
              ▾
            </button>
          </div>
        </div>

        <div className="space-y-2 px-2.5 py-2">
          {busbars.map((bus) => (
            <div key={bus.id}>
              <div className="text-[9px] uppercase tracking-wide text-ink3">{bus.name}</div>
              <div className="mt-0.5 h-[3px] w-full rounded bg-accent/70" />
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 gap-1 px-2.5 pb-2 min-[400px]:grid-cols-2">
          {cells.map((cell) => (
            <div
              key={cell.id}
              className={`group flex items-center gap-1 rounded-md border bg-surface2/40 px-1.5 py-1 ${roleColor(
                cell.role,
              )} ${data.jumperFirstId === cell.id ? 'ring-2 ring-accent' : ''}`}
            >
              <button
                type="button"
                className="min-w-0 flex-1 text-left"
                title={`${cell.name} · ${cell.type_name ?? ''}`}
                onClick={(event) => {
                  event.stopPropagation()
                  if (data.jumperMode && data.onCellPick) {
                    data.onCellPick(block.asset_id, cell.id, cell.name)
                  } else {
                    data.onSelectChild?.(cell.id)
                  }
                }}
              >
                <div className="truncate text-[10px] leading-tight">{cell.name}</div>
                {typeof cell.params?.cable === 'string' ? (
                  <div className="truncate text-[8px] text-ink3">{cell.params.cable}</div>
                ) : null}
              </button>
              {data.editable && data.onDeleteCell ? (
                <button
                  type="button"
                  className="hidden h-5 w-5 shrink-0 place-items-center rounded text-[10px] text-bad hover:bg-bad/10 group-hover:grid"
                  title="Удалить ячейку"
                  onClick={(event) => {
                    event.stopPropagation()
                    data.onDeleteCell?.(block.asset_id, cell.id, cell.name)
                  }}
                >
                  🗑
                </button>
              ) : null}
            </div>
          ))}
        </div>

        <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-accent" />
        <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-accent" />
      </div>
    )
  }

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
          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg"
          style={{ background: `${node.type_color ?? '#4C9AFF'}18` }}
        >
          <GostSymbol symbol={node.schema_symbol ?? 'load'} />
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
            className={`!h-5 !w-5 !border-2 md:!h-3 md:!w-3 ${
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
  const [frame, setFrame] = useState<SchemaFrame | null>(null)
  const [showFrame, setShowFrame] = useState(() => localStorage.getItem('karier-schema-frame') !== '0')

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

  const [blocks, setBlocks] = useState<SchemaBlock[]>([])
  const [legend, setLegend] = useState<{ symbol: string; title: string; count: number }[]>([])
  const [showLegend, setShowLegend] = useState(false)
  const [jumperMode, setJumperMode] = useState(false)
  const [jumperFirst, setJumperFirst] = useState<{ blockId: string; cellId: string; name: string } | null>(null)
  const [jumperPair, setJumperPair] = useState<{ blockId: string; from: string; fromName: string; to: string; toName: string } | null>(null)
  const [jumperLabel, setJumperLabel] = useState('')

  useEffect(() => {
    gisApi
      .schemaBlocks()
      .then(setBlocks)
      .catch(() => setBlocks([]))
    gisApi
      .schemaLegend()
      .then(setLegend)
      .catch(() => setLegend([]))
  }, [])

  const handleCellPick = useCallback(
    (blockId: string, cellId: string, name: string) => {
      if (!jumperMode) return
      if (!jumperFirst) {
        setJumperFirst({ blockId, cellId, name })
        setStatus(`Перемычка: выбрана «${name}», укажите вторую ячейку`)
        return
      }
      if (jumperFirst.blockId !== blockId) {
        setError('Перемычку можно сделать только внутри одного блока')
        return
      }
      if (jumperFirst.cellId === cellId) {
        setError('Выберите другую ячейку')
        return
      }
      setJumperPair({
        blockId,
        from: jumperFirst.cellId,
        fromName: jumperFirst.name,
        to: cellId,
        toName: name,
      })
      setJumperFirst(null)
      setJumperLabel('')
    },
    [jumperMode, jumperFirst],
  )

  const createJumperLink = useCallback(async () => {
    if (!jumperPair) return
    try {
      await gisApi.createJumper(jumperPair.blockId, jumperPair.from, jumperPair.to, jumperLabel || undefined)
      setStatus(`Перемычка ${jumperPair.fromName} → ${jumperPair.toName} создана`)
      setJumperPair(null)
      setJumperMode(false)
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать перемычку')
    }
  }, [jumperPair, jumperLabel, onGraphChanged])

  const handleAddCell = useCallback(
    async (assetId: string) => {
      const label = `ф.${10 + Math.floor(Math.random() * 80)}-6`
      try {
        await gisApi.addBlockCell(assetId, label)
        setStatus(`Добавлена ячейка ${label}`)
        onGraphChanged()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось добавить ячейку')
      }
    },
    [onGraphChanged],
  )

  const handleDeleteCell = useCallback(
    async (assetId: string, cellId: string, name: string) => {
      if (!window.confirm(`Удалить ячейку «${name}»?`)) return
      try {
        await gisApi.deleteBlockCell(assetId, cellId)
        setStatus(`Ячейка «${name}» удалена`)
        onGraphChanged()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось удалить ячейку')
      }
    },
    [onGraphChanged],
  )

  const handleToggleCollapse = useCallback(
    async (assetId: string, collapsed: boolean) => {
      try {
        await gisApi.collapseBlock(assetId, collapsed)
        onGraphChanged()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось свернуть блок')
      }
    },
    [onGraphChanged],
  )

  const placeBlock = useCallback(
    async (code: string) => {
      try {
        await gisApi.instantiateBlock(code, 120, 140)
        setStatus('Блок установлен на схему')
        onGraphChanged()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось поставить блок')
      }
    },
    [onGraphChanged],
  )

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
          block: graph.blocks.find((item) => item.asset_id === node.id),
          onSelectChild: onSelect,
          onAddCell: handleAddCell,
          onDeleteCell: handleDeleteCell,
          onToggleCollapse: handleToggleCollapse,
          jumperMode,
          jumperFirstId: jumperFirst?.cellId ?? null,
          onCellPick: handleCellPick,
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
  }, [graph, setNodes, setEdges, handleAddCell, handleDeleteCell, handleToggleCollapse, onSelect, jumperMode, jumperFirst, handleCellPick])

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
    gisApi
      .getSchemaFrame()
      .then(setFrame)
      .catch(() => setFrame(null))
  }, [])

  useEffect(() => {
    localStorage.setItem('karier-schema-frame', showFrame ? '1' : '0')
  }, [showFrame])

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

  const applyTemplate = () => {
    const layout: Record<string, { x: number; y: number }> = {}
    const top = nodes.filter((node) => ['source', 'generator'].includes(node.data.node.schema_symbol ?? 'load'))
    const buses = nodes.filter((node) => node.data.node.schema_symbol === 'busbar')
    const rest = nodes.filter((node) => !top.includes(node) && !buses.includes(node))

    top.forEach((node, index) => {
      layout[node.id] = { x: 80 + index * 280, y: 0 }
    })
    buses.forEach((node, index) => {
      layout[node.id] = { x: 40, y: 200 + index * 140 }
    })
    rest.forEach((node, index) => {
      const perRow = 6
      layout[node.id] = {
        x: 60 + (index % perRow) * 240,
        y: 420 + Math.floor(index / perRow) * 160,
      }
    })

    setNodes((current) => current.map((node) => ({ ...node, position: layout[node.id] ?? node.position })))
    setDirty(true)
    setStatus('Шаблон ГОСТ применён — проверьте и сохраните раскладку')
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
      {canEdit && blocks.length > 0 ? (
        <div className="absolute left-2 top-16 z-10 max-h-[55%] w-[196px] overflow-y-auto rounded-xl border border-line bg-surface1/95 p-2 text-[12px] backdrop-blur">
          <div className="mb-1 text-[10px] uppercase tracking-wide text-ink3">Библиотека блоков</div>
          <div className="space-y-1">
            {blocks.map((block) => (
              <button
                key={block.id}
                type="button"
                className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] text-ink2 hover:bg-surface2 hover:text-ink"
                title={`${block.nodes_count} элементов · ${block.external_ports} внешних портов`}
                onClick={() => void placeBlock(block.code)}
              >
                <span>{block.icon ?? '▣'}</span>
                <span className="min-w-0 flex-1 truncate">{block.name}</span>
                <span className="text-[10px] text-ink3">{block.nodes_count}</span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

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
                title="Разложить по ГОСТ-шаблону: источники сверху, шины в середине, потребители снизу"
                onClick={applyTemplate}
              >
                Шаблон
              </button>
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={showFrame} onChange={(e) => setShowFrame(e.target.checked)} />
                Рамка
              </label>
              <button
                type="button"
                className={`btn-ghost h-8 px-3 ${jumperMode ? 'ring-1 ring-accent' : ''}`}
                title="Перемычка между ячейками одного блока"
                onClick={() => {
                  setJumperMode((value) => !value)
                  setJumperFirst(null)
                  setJumperPair(null)
                }}
              >
                🔗 Перемычка
              </button>
              <button type="button" className="btn-ghost h-8 px-3" onClick={() => setShowLegend((v) => !v)}>
                Легенда
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
        <Controls
          showInteractive={false}
          position="bottom-right"
          style={{ bottom: 'calc(var(--bottom-nav) + 12px)', right: 12 }}
        />
      </ReactFlow>

      {showLegend && legend.length > 0 ? (
        <div className="absolute right-3 top-16 z-[12] max-h-[55%] w-[220px] overflow-y-auto rounded-xl border border-line bg-surface1/95 p-2 text-[11px] shadow-lg">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wide text-ink3">Условные обозначения</span>
            <button type="button" className="text-[11px] text-ink3" onClick={() => setShowLegend(false)}>✕</button>
          </div>
          <div className="space-y-1">
            {legend.map((item) => (
              <div key={item.symbol} className="flex items-center justify-between gap-2">
                <span className="truncate">{item.title}</span>
                <span className="text-ink3">{item.count}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}


      {jumperPair ? (
        <div className="absolute inset-x-3 bottom-20 z-[13] rounded-xl border border-accent/50 bg-surface1 p-3 text-[12px] shadow-xl sm:left-auto sm:right-3 sm:w-[320px]">
          <div className="mb-2 font-semibold text-ink">
            Перемычка: {jumperPair.fromName} → {jumperPair.toName}
          </div>
          <label className="mb-2 block text-[11px] text-ink3">
            Название (необязательно)
            <input
              className="input mt-1 h-8"
              value={jumperLabel}
              onChange={(event) => setJumperLabel(event.target.value)}
              placeholder="например, перемычка секций"
            />
          </label>
          <div className="flex gap-2">
            <button type="button" className="btn-primary h-8 flex-1" onClick={() => void createJumperLink()}>
              Создать
            </button>
            <button type="button" className="btn-ghost h-8" onClick={() => setJumperPair(null)}>
              Отмена
            </button>
          </div>
        </div>
      ) : null}

      {frame && showFrame ? <SchemaFrameOverlay frame={frame} compact={false} /> : null}

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
