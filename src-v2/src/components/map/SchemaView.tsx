import { Fragment, memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
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
  ViewportPortal,
} from '@xyflow/react'
import dagre from 'dagre'
import '@xyflow/react/dist/style.css'
import type { AssetPort, GraphNode, TopologyGraph } from '../../lib/gis'
import { downloadDxf } from '../../lib/dxf'
import { GostSymbol, SchemaFrameOverlay } from './GostSymbols'
import { SnapshotsPanel } from './SnapshotsPanel'
import { AddToSchemaPanel } from './AddToSchemaPanel'
import { BulkCellsDialog } from './BulkCellsDialog'
import type { SchemaBlock, SchemaFrame, GraphBlock } from '../../lib/gis'
import { POWER_COLOR, STATUS_LABEL, gisApi } from '../../lib/gis'
import { ApiError } from '../../lib/api'
import { ConfirmDialog } from '../ui'

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
  onMoveCell?: (assetId: string, cellId: string, name: string) => void
  onToggleCollapse?: (assetId: string, collapsed: boolean) => void
  jumperMode?: boolean
  jumperFirstId?: string | null
  activeConnection?: { nodeId: string; portId: string; kind: string; voltage: number | null } | null
  onCellPick?: (blockId: string, cellId: string, name: string) => void
  linkCellsMode?: boolean
  onCellLink?: (blockId: string, cellId: string, name: string) => void
  cellLinkFirstId?: string | null
  onAddCellsBulk?: (assetId: string) => void
  cableMode?: boolean
  onCellCable?: (blockId: string, cellId: string, name: string) => void
  cableFromCellId?: string | null
}

function portLabel(port: AssetPort): string {
  const kind =
    port.kind === 'in' ? 'Ввод' : port.kind === 'out' ? 'Отходящая' : 'Двунаправленный'
  return `${kind} ${port.code}${port.nominal_voltage_kv ? ` · ${port.nominal_voltage_kv} кВ` : ''}`
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

function NodeHandles({ color = 'accent', dimmed = false }: { color?: string; dimmed?: boolean }) {
  const cls = `!h-1.5 !w-1.5 !border-0 !bg-${color} ${dimmed ? 'opacity-20' : ''}`
  return (
    <>
      <Handle id="l-in" type="target" position={Position.Left} className={cls} />
      <Handle id="r-in" type="target" position={Position.Right} className={cls} />
      <Handle id="t-in" type="target" position={Position.Top} className={cls} />
      <Handle id="b-in" type="target" position={Position.Bottom} className={cls} />
      <Handle id="l-out" type="source" position={Position.Left} className={cls} />
      <Handle id="r-out" type="source" position={Position.Right} className={cls} />
      <Handle id="t-out" type="source" position={Position.Top} className={cls} />
      <Handle id="b-out" type="source" position={Position.Bottom} className={cls} />
    </>
  )
}


function AssetNodeImpl({ data, selected }: NodeProps<Node<AssetNodeData>>) {
  const { node, editable, portDrag, portPositions, onPortMove } = data
  const blockBox = useRef<HTMLDivElement | null>(null)
  const cellRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const [jumperLines, setJumperLines] = useState<
    { id: string; x1: number; y1: number; x2: number; y2: number; label: string | null }[]
  >([])
  // под напряжением — красный, обесточено/отключено — зелёный
  const powerColor = node.energized || node.status === 'on' ? POWER_COLOR.on : POWER_COLOR.off
  const dim = !node.energized

  useLayoutEffect(() => {
    if (!data.block || data.block.collapsed) {
      setJumperLines([])
      return
    }
    const blockNow = data.block
    let frame = 0
    const measure = () => {
      const box = blockBox.current
      if (!box) return
      const boxRect = box.getBoundingClientRect()
      if (!boxRect.width) {
        frame = requestAnimationFrame(measure)
        return
      }
      const lines: { id: string; x1: number; y1: number; x2: number; y2: number; label: string | null }[] = []
      for (const jumper of blockNow.jumpers ?? []) {
        const a = cellRefs.current[jumper.from_cell_id]
        const b = cellRefs.current[jumper.to_cell_id]
        if (!a || !b) continue
        const ra = a.getBoundingClientRect()
        const rb = b.getBoundingClientRect()
        if (!ra.width || !rb.width) continue
        lines.push({
          id: jumper.id,
          x1: ra.right - boxRect.left,
          y1: ra.top + ra.height / 2 - boxRect.top,
          x2: rb.left - boxRect.left,
          y2: rb.top + rb.height / 2 - boxRect.top,
          label: jumper.label,
        })
      }
      setJumperLines(lines)
    }
    frame = requestAnimationFrame(() => requestAnimationFrame(measure))
    const onResize = () => measure()
    window.addEventListener('resize', onResize)
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', onResize)
    }
  }, [data.block])


  if (data.block) {
    const block = data.block
    const busbars = block.children.filter((child) => child.role === 'busbar')
    const cells = block.children.filter((child) => child.role !== 'busbar')
    const jumperCells = new Set<string>()
    for (const jumper of block.jumpers ?? []) {
      jumperCells.add(jumper.from_cell_id)
      jumperCells.add(jumper.to_cell_id)
    }
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
              <div className="text-[10px] text-ink3">{cells.length + busbars.length} элементов</div>
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
          <NodeHandles />
        </div>
      )
    }

    return (
      <div
        ref={blockBox}
        className={`relative w-[320px] max-w-[calc(100vw-28px)] rounded-xl border-2 ${
          block.kind === 'contour'
            ? 'border-dashed border-accent/35 bg-surface1/70'
            : 'border-accent/45 bg-surface1/95'
        } ${selected ? 'ring-2 ring-accent' : ''}`}
        style={
          block.kind === 'contour'
            ? { width: block.width ?? 320, minHeight: block.height ?? 220 }
            : undefined
        }
      >
        <div className="flex items-start justify-between gap-2 border-b border-line px-2.5 py-2">
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold leading-tight text-ink">{block.name}</div>
            <div className="mt-0.5 text-[10px] text-ink3">
              {cells.length} ячеек · {busbars.length} секции
            </div>
          </div>
          <div className="flex items-center gap-1">
            {data.editable && data.onAddCell ? (
              <button
                type="button"
                className="btn-ghost h-6 px-1.5 text-[11px]"
                title="Добавить ячейки: пачкой, со сквозной нумерацией и секциями"
                onClick={(event) => {
                  event.stopPropagation()
                  if (data.onAddCellsBulk) data.onAddCellsBulk(block.asset_id)
                  else data.onAddCell?.(block.asset_id)
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
          {cells.map((cell, cellIndex) => {
            const section = (cell.params?.section as string | undefined) ?? null
            const previousSection =
              cellIndex > 0 ? ((cells[cellIndex - 1].params?.section as string | undefined) ?? null) : null
            const showSection = Boolean(section) && section !== previousSection
            return (
            <Fragment key={cell.id}>
              {showSection ? (
                <div className="col-span-full mt-1 flex items-center gap-2 text-[9px] uppercase tracking-wide text-ink3">
                  <span className="h-px flex-1 bg-line" />
                  {section}
                  <span className="h-px flex-1 bg-line" />
                </div>
              ) : null}
            <div
              key={cell.id}
              ref={(el) => { cellRefs.current[cell.id] = el }}
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
                  } else if (data.linkCellsMode && data.onCellLink) {
                    data.onCellLink(block.asset_id, cell.id, cell.name)
                  } else if (data.cableMode && data.onCellCable) {
                    data.onCellCable(block.asset_id, cell.id, cell.name)
                  } else {
                    data.onSelectChild?.(cell.id)
                  }
                }}
              >
                <div className="truncate text-[10px] leading-tight">{cell.name}</div>
                {typeof cell.params?.cable === 'string' ? (
                  <div className="truncate text-[8px] text-ink3">{cell.params.cable}</div>
                ) : null}
                {jumperCells.has(cell.id) ? (
                  <div className="mt-0.5 inline-flex items-center gap-0.5 rounded bg-[#C4A1FF]/20 px-1 text-[8px] text-[#C4A1FF]">
                    ⇄ перемычка
                  </div>
                ) : null}
              </button>
              {data.editable && data.onMoveCell ? (
                <button
                  type="button"
                  className="hidden h-5 w-5 shrink-0 place-items-center rounded text-[10px] text-accent hover:bg-accent/10 group-hover:grid"
                  title="Перенести в другой блок или контур"
                  onClick={(event) => {
                    event.stopPropagation()
                    data.onMoveCell?.(block.asset_id, cell.id, cell.name)
                  }}
                >
                  ⇄
                </button>
              ) : null}
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
            </Fragment>
            )
          })}
        </div>

        {jumperLines.length > 0 ? (
          <svg className="pointer-events-none absolute inset-0 z-[8] h-full w-full overflow-visible">
            {jumperLines.map((line) => (
              <g key={line.id}>
                <line
                  x1={line.x1}
                  y1={line.y1}
                  x2={line.x2}
                  y2={line.y2}
                  stroke="#C4A1FF"
                  strokeWidth={1.6}
                  strokeDasharray="4 3"
                  style={{ pointerEvents: 'stroke' }}
                >
                  <title>{line.label ? `Перемычка: ${line.label}` : 'Перемычка'}</title>
                </line>
              </g>
            ))}
          </svg>
        ) : null}

        <NodeHandles />
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
      style={node.grounded ? undefined : { borderColor: powerColor }}
    >
      <div className="flex items-center gap-2">
        <span
          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg"
          style={{ background: `${node.type_color ?? '#4C9AFF'}18` }}
        >
          <GostSymbol symbol={node.schema_symbol ?? 'load'} />
        </span>
        <div className="min-w-0">
          <div className="truncate text-[12px] font-semibold text-ink">{node.name}</div>
          <div className="truncate text-[10px] text-ink3">{node.type_name}</div>
        </div>
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-[10px]">
        <span style={{ color: powerColor }}>●</span>
        <span className="text-ink2">{STATUS_LABEL[node.status] ?? node.status}</span>
        {node.grounded ? <span className="text-ground">⏚</span> : null}
        {node.is_source ? <span className="ml-auto text-warm">источник</span> : null}
      </div>

      {node.ports.map((port) => {
        const position = portPositions[port.id] ?? { x: 0.5, y: 0.5 }
        const interactive = editable && !portDrag
        const active = data.activeConnection
        const otherNode = active != null && active.nodeId !== node.id
        const compatible = Boolean(
          active &&
            otherNode &&
            port.kind !== 'out' &&
            (active.voltage == null ||
              port.nominal_voltage_kv == null ||
              active.voltage === port.nominal_voltage_kv),
        )
        const incompatible = Boolean(active && otherNode && !compatible)
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
            className={`!h-5 !w-5 !border-2 md:!h-3 md:!w-3 transition-all ${compatible ? '!border-ok !bg-ok/40 !h-6 !w-6 animate-pulse' : ''} ${incompatible ? '!opacity-20' : ''} ${
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

      <NodeHandles color="line" dimmed={Boolean(data.activeConnection)} />
    </div>
  )
}

/**
 * Сравнение пропсов узла для React.memo: перерисовываем узел только когда изменилось
 * его собственное выделение, данные объекта/блока, флаги режимов или стабильные обработчики.
 * Благодаря этому смена selectedId перерисовывает два узла (был/стал), а не все 200+.
 */
export function areNodePropsEqual(
  prev: NodeProps<Node<AssetNodeData>>,
  next: NodeProps<Node<AssetNodeData>>,
): boolean {
  if (prev.selected !== next.selected) return false
  const a = prev.data
  const b = next.data
  return (
    a.node === b.node &&
    a.block === b.block &&
    a.editable === b.editable &&
    a.portDrag === b.portDrag &&
    a.portPositions === b.portPositions &&
    a.jumperMode === b.jumperMode &&
    a.jumperFirstId === b.jumperFirstId &&
    a.linkCellsMode === b.linkCellsMode &&
    a.cellLinkFirstId === b.cellLinkFirstId &&
    a.cableMode === b.cableMode &&
    a.cableFromCellId === b.cableFromCellId &&
    a.activeConnection === b.activeConnection &&
    a.onPortMove === b.onPortMove &&
    a.onSelectChild === b.onSelectChild &&
    a.onAddCell === b.onAddCell &&
    a.onAddCellsBulk === b.onAddCellsBulk &&
    a.onDeleteCell === b.onDeleteCell &&
    a.onMoveCell === b.onMoveCell &&
    a.onToggleCollapse === b.onToggleCollapse &&
    a.onCellPick === b.onCellPick &&
    a.onCellLink === b.onCellLink &&
    a.onCellCable === b.onCellCable
  )
}

const AssetNode = memo(AssetNodeImpl, areNodePropsEqual)

const nodeTypes = { asset: AssetNode }

/**
 * dagre-раскладка. Если передан `only` — раскладываются только эти узлы (узлы без
 * сохранённых schema_x/schema_y); если таких нет, layout не запускается вовсе.
 * Без `only` раскладываются все узлы — это режим кнопки «Авто-раскладка».
 */
export function dagrePositions(
  graph: TopologyGraph,
  only?: ReadonlySet<string>,
): Record<string, XYPosition> {
  const result: Record<string, XYPosition> = {}
  const wanted = (id: string) => !only || only.has(id)
  let count = 0
  graph.nodes.forEach((node) => {
    if (wanted(node.id)) count += 1
  })
  if (count === 0) return result

  const layout = new dagre.graphlib.Graph()
  layout.setDefaultEdgeLabel(() => ({}))
  layout.setGraph({ rankdir: 'TB', nodesep: 48, ranksep: 90, marginx: 24, marginy: 24 })

  graph.nodes.forEach((node) => {
    if (wanted(node.id)) layout.setNode(node.id, { width: NODE_W, height: NODE_H })
  })
  graph.edges.forEach((edge) => {
    if (layout.hasNode(edge.from_asset_id) && layout.hasNode(edge.to_asset_id)) {
      layout.setEdge(edge.from_asset_id, edge.to_asset_id)
    }
  })
  dagre.layout(layout)

  graph.nodes.forEach((node) => {
    if (!wanted(node.id)) return
    const point = layout.node(node.id)
    result[node.id] = {
      x: Math.round(((point?.x ?? 0) - NODE_W / 2) / GRID) * GRID,
      y: Math.round(((point?.y ?? 0) - NODE_H / 2) / GRID) * GRID,
    }
  })
  return result
}

/** Позиции узлов: сохранённые в БД приоритетнее, dagre — только для узлов без координат. */
export function nodePositions(graph: TopologyGraph): Record<string, XYPosition> {
  const missing = new Set<string>()
  graph.nodes.forEach((node) => {
    if (node.schema_x == null || node.schema_y == null) missing.add(node.id)
  })
  const auto = missing.size > 0 ? dagrePositions(graph, missing) : {}
  const result: Record<string, XYPosition> = {}
  graph.nodes.forEach((node) => {
    result[node.id] =
      node.schema_x != null && node.schema_y != null
        ? { x: node.schema_x, y: node.schema_y }
        : auto[node.id] ?? { x: 0, y: 0 }
  })
  return result
}

export function buildEdges(graph: TopologyGraph, positions: Record<string, XYPosition>): Edge[] {
  return graph.edges.map((edge) => {
    const from = positions[edge.from_asset_id]
    const to = positions[edge.to_asset_id]
    let sourceHandle = 'r-out'
    let targetHandle = 'l-in'
    if (from && to) {
      const dx = to.x - from.x
      const dy = to.y - from.y
      if (Math.abs(dy) >= Math.abs(dx) * 0.75) {
        if (dy >= 0) {
          sourceHandle = 'b-out'
          targetHandle = 't-in'
        } else {
          sourceHandle = 't-out'
          targetHandle = 'b-in'
        }
      } else if (dx < 0) {
        sourceHandle = 'l-out'
        targetHandle = 'r-in'
      }
    }
    const open = edge.state !== 'connected'
    const jumper = edge.link_type === 'jumper'
    return {
      id: edge.id,
      type: 'smoothstep',
      pathOptions: { borderRadius: 8 },
      sourceHandle,
      targetHandle,
      source: edge.from_asset_id,
      target: edge.to_asset_id,
      label: edge.label,
      animated: false,
      style: {
        stroke: open ? POWER_COLOR.off : POWER_COLOR.on,
        strokeWidth: open ? 1.2 : 1.8,
        strokeDasharray: jumper ? '2 4' : open ? '6 4' : undefined,
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

/** Флаги режимов, которые видны узлу; обновляются точечно, без пересборки графа. */
export type NodeModeFlags = {
  editable: boolean
  portDrag: boolean
  jumperMode: boolean
  jumperFirstId: string | null
  linkCellsMode: boolean
  cellLinkFirstId: string | null
  cableMode: boolean
  cableFromCellId: string | null
  activeConnection: { nodeId: string; portId: string; kind: string; voltage: number | null } | null
  draggable: boolean
}

/**
 * Точечно применяет флаги режимов к узлам: если у узла ничего не изменилось,
 * возвращается тот же объект, а весь массив — тот же, если не изменился ни один узел.
 * Dagre/связи при этом не пересчитываются.
 */
export function applyNodeModes(
  nodes: Node<AssetNodeData>[],
  flags: NodeModeFlags,
): Node<AssetNodeData>[] {
  let changed = false
  const next = nodes.map((node) => {
    const data = node.data
    if (
      data.editable === flags.editable &&
      data.portDrag === flags.portDrag &&
      data.jumperMode === flags.jumperMode &&
      data.jumperFirstId === flags.jumperFirstId &&
      data.linkCellsMode === flags.linkCellsMode &&
      data.cellLinkFirstId === flags.cellLinkFirstId &&
      data.cableMode === flags.cableMode &&
      data.cableFromCellId === flags.cableFromCellId &&
      data.activeConnection === flags.activeConnection &&
      node.draggable === flags.draggable
    ) {
      return node
    }
    changed = true
    return {
      ...node,
      draggable: flags.draggable,
      data: {
        ...data,
        editable: flags.editable,
        portDrag: flags.portDrag,
        jumperMode: flags.jumperMode,
        jumperFirstId: flags.jumperFirstId,
        linkCellsMode: flags.linkCellsMode,
        cellLinkFirstId: flags.cellLinkFirstId,
        cableMode: flags.cableMode,
        cableFromCellId: flags.cableFromCellId,
        activeConnection: flags.activeConnection,
      },
    }
  })
  return changed ? next : nodes
}

/** Точечно обновляет выделение: меняются только два узла (бывший и новый), не все. */
export function applySelection(
  nodes: Node<AssetNodeData>[],
  selectedId: string | null,
): Node<AssetNodeData>[] {
  let changed = false
  const next = nodes.map((node) => {
    const selected = node.id === selectedId
    if (node.selected === selected) return node
    changed = true
    return { ...node, selected }
  })
  return changed ? next : nodes
}

/** Коды отказа переноса → короткая причина для подсветки опасности. */
const RELOCATE_DANGER: Record<string, string> = {
  'schema.move.voltage_mismatch': 'Нельзя: напряжения объектов не совпадают',
  'schema.move.direction_conflict': 'Нельзя: роль/направление не совпадает с шаблоном блока',
  'schema.move.cycle': 'Нельзя: перенос внутрь собственного потомка',
  'schema.move.self': 'Нельзя: перенос объекта в себя',
  'schema.move.not_container': 'Нельзя: выбранный объект не является контейнером',
  'schema.move.container': 'Нельзя: контейнеры не переносятся',
  'structural_protected': 'Нельзя: структурный элемент блока защищён',
  'asset.out_of_bounds': 'Нельзя: точка за границами схемы',
  'schema.move.confirmation_required': 'Перенос изменит связи — нужно подтверждение',
}

export function relocateDangerText(err: ApiError): string {
  return RELOCATE_DANGER[err.code] ?? `Перенос отклонён: ${err.message}`
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
  const [activeConnection, setActiveConnection] = useState<{
    nodeId: string
    portId: string
    kind: string
    voltage: number | null
  } | null>(null)
  const [menu, setMenu] = useState<{ x: number; y: number; type: 'node' | 'edge' | 'pane'; id?: string } | null>(null)
  const dragStartPositions = useRef<Record<string, XYPosition> | null>(null)
  // История действий: перемещение узлов хранится локально (позиции), а мутации
  // схемы — как пары обратных вызовов на сервере (создал ↔ удалил, удалил ↔ вернул).
  type HistoryEntry =
    | { kind: 'positions'; before: Record<string, XYPosition>; after: Record<string, XYPosition> }
    | { kind: 'command'; label: string; undo: () => Promise<void>; redo: () => Promise<void> }
  const historyRef = useRef<HistoryEntry[]>([])
  const historyIndex = useRef(0)
  const [, setHistoryVersion] = useState(0)

  const pushHistory = useCallback((entry: HistoryEntry) => {
    historyRef.current = historyRef.current.slice(0, historyIndex.current)
    historyRef.current.push(entry)
    historyIndex.current = historyRef.current.length
    setHistoryVersion((value) => value + 1)
  }, [])

  const pushCommand = useCallback(
    (label: string, undoAction: () => Promise<void>, redoAction: () => Promise<void>) => {
      pushHistory({ kind: 'command', label, undo: undoAction, redo: redoAction })
    },
    [pushHistory],
  )
  const [guides, setGuides] = useState<{ x?: number; y?: number } | null>(null)
  const [cellLinkMode, setCellLinkMode] = useState(false)
  const [cellLinkFirst, setCellLinkFirst] = useState<{ blockId: string; cellId: string; name: string } | null>(null)
  const [poleDialog, setPoleDialog] = useState<'generate' | 'renumber' | null>(null)
  const [polePick, setPolePick] = useState<'polyline' | null>(null)
  const [polePath, setPolePath] = useState<Array<{ x: number; y: number }>>([])
  const [poleAnchor, setPoleAnchor] = useState<{ id: string; name: string } | null>(null)
  const [anchorPick, setAnchorPick] = useState(false)
  const [renumberMode, setRenumberMode] = useState<'all' | 'chain'>('chain')
  const [poleForm, setPoleForm] = useState({ count: '5', start: '1', step: '1', prefix: 'оп.' })
  const [snapshotsOpen, setSnapshotsOpen] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [bulkParent, setBulkParent] = useState<{ id: string; name: string } | null>(null)
  const [cableMode, setCableMode] = useState(false)
  const [cableFrom, setCableFrom] = useState<{ cellId: string; name: string; blockId: string } | null>(null)
  const wrapperRef = useRef<HTMLDivElement | null>(null)
  const { screenToFlowPosition } = useReactFlow()

  const focusAsset = useCallback(
    (assetId: string) => {
      // Новый элемент может оказаться далеко от текущего вида — подводим камеру,
      // иначе пользователь не видит результата («ничего не добавилось»).
      // два прохода: первый — сразу после ответа API, второй — когда граф
      // перерисован и узел уже есть в ReactFlow
      const focus = (delay: number) =>
        setTimeout(() => {
          try {
            fitView({ nodes: [{ id: assetId }], padding: 1.6, duration: 400, maxZoom: 1.2 })
          } catch {
            fitView({ padding: 0.5, duration: 400 })
          }
        }, delay)
      focus(500)
      focus(1400)
    },
    [fitView],
  )

  const [cableMark, setCableMark] = useState('')
  const [linkType, setLinkType] = useState('cable')
  const [edgeDraft, setEdgeDraft] = useState<EdgeDraft | null>(null)
  const [confirmRemoveEdge, setConfirmRemoveEdge] = useState(false)
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
  // Подсказки-подсказки обратной связи: не перекрывают кнопки и скрываются по таймауту
  const [dangerHint, setDangerHint] = useState<string | null>(null)
  const [showDragHint, setShowDragHint] = useState(true)
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

  const handleCellLink = useCallback(async (blockId: string, cellId: string, name: string) => {
    if (!cellLinkMode) return
    if (!cellLinkFirst) {
      setCellLinkFirst({ blockId, cellId, name })
      setStatus(`Связь ячеек: выбрана «${name}», кликните принимающую ячейку другого комплекта`)
      return
    }
    if (cellLinkFirst.blockId === blockId) {
      setError('Выберите ячейку другого комплекта')
      return
    }
    try {
      const [a, b] = await Promise.all([gisApi.asset(cellLinkFirst.blockId), gisApi.asset(blockId)])
      await Promise.all([gisApi.ensurePorts(a.id), gisApi.ensurePorts(b.id)])
      const [freshA, freshB] = await Promise.all([gisApi.asset(a.id), gisApi.asset(b.id)])
      const fromPort = freshA.ports.find((port) => port.kind !== 'in') ?? freshA.ports[0]
      const toPort = freshB.ports.find((port) => port.kind !== 'out') ?? freshB.ports[0]
      if (!fromPort || !toPort) {
        setError('У комплектов нет портов для связи')
        return
      }
      const created = await gisApi.createLink({
        from_port_id: fromPort.id,
        to_port_id: toPort.id,
        link_type: 'cable',
        cable_mark: `${cellLinkFirst.name} → ${name}`,
      })
      let linkId = created.id
      pushCommand(
        'связь ячеек',
        async () => {
          await gisApi.deleteLink(linkId)
        },
        async () => {
          const again = await gisApi.restoreLink(linkId)
          linkId = again.id
        },
      )
      setStatus(`Связь создана: ${cellLinkFirst.name} → ${name}`)
      setCellLinkFirst(null)
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось соединить ячейки')
    }
  }, [cellLinkMode, cellLinkFirst, onGraphChanged, pushCommand])

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
      const created = await gisApi.createJumper(jumperPair.blockId, jumperPair.from, jumperPair.to, jumperLabel || undefined)
      let linkId = created.id
      pushCommand(
        'перемычка',
        async () => {
          await gisApi.deleteLink(linkId)
        },
        async () => {
          const again = await gisApi.restoreLink(linkId)
          linkId = again.id
        },
      )
      setStatus(`Перемычка ${jumperPair.fromName} → ${jumperPair.toName} создана`)
      setJumperPair(null)
      setJumperMode(false)
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать перемычку')
    }
  }, [jumperPair, jumperLabel, onGraphChanged, pushCommand])

  const handleBulkCells = useCallback(
    (assetId: string) => {
      const block = graph.blocks.find((item) => item.asset_id === assetId)
      setBulkParent({ id: assetId, name: block?.name ?? graph.nodes.find((n) => n.id === assetId)?.name ?? 'Блок' })
    },
    [graph.blocks, graph.nodes],
  )

  const handleBulkCreated = useCallback(
    (cells: Array<{ id: string; name: string }>, parentId: string) => {
      const ids = cells.map((cell) => cell.id)
      pushCommand(
        `добавление ячеек (${cells.length})`,
        async () => {
          for (const id of ids) {
            await gisApi.deleteBlockCell(parentId, id)
          }
        },
        async () => {
          for (const id of ids) {
            await gisApi.restoreAsset(id)
          }
        },
      )
      onGraphChanged()
      focusAsset(parentId)
      setStatus(`Добавлено ячеек: ${cells.length}`)
    },
    [onGraphChanged, pushCommand, focusAsset],
  )

  const handleCellCable = useCallback(
    (blockId: string, cellId: string, name: string) => {
      if (!cableMode) return
      setCableFrom({ cellId, name, blockId })
      setStatus(`Кабель: выбран «${name}». Кликните опору, КТП или разъединитель`)
    },
    [cableMode],
  )

  const createCableTo = useCallback(
    async (toAssetId: string) => {
      if (!cableFrom) return
      const mark = window.prompt('Марка кабеля (например, Ф-7К)', '')
      if (mark === null) return
      setSaving(true)
      setError(null)
      try {
        const link = await gisApi.createCellCable(cableFrom.cellId, {
          to_asset_id: toAssetId,
          cable_mark: mark.trim() || undefined,
        })
        pushCommand(
          'кабельная связь',
          async () => {
            await gisApi.deleteLink(link.id)
          },
          async () => {
            await gisApi.restoreLink(link.id)
          },
        )
        setCableFrom(null)
        setCableMode(false)
        onGraphChanged()
        setStatus('Кабельная связь создана')
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось создать кабель')
      } finally {
        setSaving(false)
      }
    },
    [cableFrom, onGraphChanged, pushCommand],
  )

  const handleLineEquipment = useCallback(
    (assetId: string, linkId: string | null, title: string) => {
      pushCommand(
        `оборудование линии «${title}»`,
        async () => {
          if (linkId) await gisApi.deleteLink(linkId)
          await gisApi.remove(assetId)
        },
        async () => {
          await gisApi.restoreAsset(assetId)
          if (linkId) await gisApi.restoreLink(linkId)
        },
      )
      onGraphChanged()
      focusAsset(assetId)
      setStatus(`Оборудование «${title}» добавлено в линию`)
    },
    [pushCommand, onGraphChanged, focusAsset],
  )
  const handleAddCell = useCallback(
    async (assetId: string) => {
      const suggested = `ф.${10 + Math.floor(Math.random() * 80)}-6`
      const input = window.prompt('Название ячейки', suggested)
      if (input === null) return
      const label = input.trim() || suggested
      try {
        const created = await gisApi.addBlockCell(assetId, label)
        let cellId = created.id
        pushCommand(
          'добавление ячейки',
          async () => {
            await gisApi.deleteBlockCell(assetId, cellId)
          },
          async () => {
            const again = await gisApi.addBlockCell(assetId, label)
            cellId = again.id
          },
        )
        setStatus(`Добавлена ячейка ${label}`)
        onGraphChanged()
        focusAsset(assetId)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось добавить ячейку')
      }
    },
    [onGraphChanged, pushCommand, focusAsset],
  )

  const handleDeleteCell = useCallback(
    async (assetId: string, cellId: string, name: string) => {
      if (!window.confirm(`Удалить ячейку «${name}»?`)) return
      try {
        await gisApi.deleteBlockCell(assetId, cellId)
        let currentId = cellId
        pushCommand(
          'удаление ячейки',
          async () => {
            const again = await gisApi.addBlockCell(assetId, name)
            currentId = again.id
          },
          async () => {
            await gisApi.deleteBlockCell(assetId, currentId)
          },
        )
        setStatus(`Ячейка «${name}» удалена`)
        onGraphChanged()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось удалить ячейку')
      }
    },
    [onGraphChanged, pushCommand],
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

  // --- Библиотека блоков: клик ставит в центр, drag&drop — в точку сброса -----
  const [dragBlock, setDragBlock] = useState<{ code: string; name: string } | null>(null)
  const [dragOver, setDragOver] = useState<'canvas' | 'invalid' | null>(null)

  // Обратная связь не должна мешать: статус и подсказки скрываются сами
  useEffect(() => {
    if (!status) return
    const timer = setTimeout(() => setStatus(null), 8000)
    return () => clearTimeout(timer)
  }, [status])

  useEffect(() => {
    if (!dangerHint) return
    const timer = setTimeout(() => setDangerHint(null), 7000)
    return () => clearTimeout(timer)
  }, [dangerHint])

  useEffect(() => {
    if (!dragBlock) return
    setShowDragHint(true)
    const timer = setTimeout(() => setShowDragHint(false), 6000)
    return () => clearTimeout(timer)
  }, [dragBlock])
  const placingBlockRef = useRef(false)

  /** Создать блок в заданной точке схемы. Один вызов API — один блок в реестре. */
  const createBlockAt = useCallback(
    async (code: string, x: number, y: number) => {
      if (placingBlockRef.current) return
      placingBlockRef.current = true
      try {
        const created = await gisApi.instantiateBlock(code, Math.round(x), Math.round(y))
        const rootId = created.asset_id
        // Блок ставится как комплекс: корень + ячейки. Отмена должна снять их все,
        // иначе ячейки останутся в базе без родителя.
        let childIds = (await gisApi.children(rootId)).map((child) => child.id)
        pushCommand(
          'установка блока',
          async () => {
            for (const childId of childIds) {
              await gisApi.remove(childId)
            }
            await gisApi.remove(rootId)
          },
          async () => {
            await gisApi.restoreAsset(rootId)
            const restored: string[] = []
            for (const childId of childIds) {
              try {
                await gisApi.restoreAsset(childId)
                restored.push(childId)
              } catch {
                // ячейка уже активна — оставляем как есть
              }
            }
            childIds = restored
          },
        )
        setStatus(`Блок «${created.code}» установлен на схему, ячеек: ${created.children} — камера наведена`)
        focusAsset(rootId)
        onGraphChanged()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось поставить блок')
      } finally {
        placingBlockRef.current = false
      }
    },
    [focusAsset, onGraphChanged, pushCommand],
  )

  const placeBlock = useCallback(
    (code: string) => {
      const rect = wrapperRef.current?.getBoundingClientRect()
      const center = rect
        ? screenToFlowPosition({
            x: rect.left + rect.width / 2,
            y: rect.top + rect.height / 2,
          })
        : { x: 120, y: 140 }
      void createBlockAt(code, center.x, center.y)
    },
    [createBlockAt, screenToFlowPosition],
  )

  const startBlockDrag = (event: React.DragEvent<HTMLButtonElement>, block: SchemaBlock) => {
    if (!canEdit) {
      event.preventDefault()
      return
    }
    event.dataTransfer.effectAllowed = 'copy'
    event.dataTransfer.setData('application/x-karier-block', block.code)
    event.dataTransfer.setData('text/plain', block.name)
    setDragBlock({ code: block.code, name: block.name })
    setDragOver(null)
  }

  const finishBlockDrag = () => {
    setDragBlock(null)
    setDragOver(null)
  }

  const handleCanvasDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    if (!canEdit || !dragBlock) return
    event.preventDefault()
    event.stopPropagation()
    event.dataTransfer.dropEffect = 'copy'
    setDragOver((prev) => (prev === 'canvas' ? prev : 'canvas'))
  }

  const handleCanvasDragLeave = (event: React.DragEvent<HTMLDivElement>) => {
    const next = event.relatedTarget
    if (!(next instanceof Element) || !event.currentTarget.contains(next)) setDragOver(null)
  }

  const handleCanvasDrop = (event: React.DragEvent<HTMLDivElement>) => {
    if (!canEdit) return
    event.preventDefault()
    event.stopPropagation()
    const code = event.dataTransfer.getData('application/x-karier-block') || dragBlock?.code
    const point = screenToFlowPosition({ x: event.clientX, y: event.clientY })
    setDragBlock(null)
    setDragOver(null)
    if (!code) return
    void createBlockAt(code, point.x, point.y)
  }

  // Перетаскивание над панелями/тулбаром — недопустимая зона (drop туда не создаёт блок).
  const handleRootDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    if (!dragBlock) return
    if (event.defaultPrevented) return
    setDragOver((prev) => (prev === 'invalid' ? prev : 'invalid'))
  }

  const handleRootDragLeave = (event: React.DragEvent<HTMLDivElement>) => {
    const next = event.relatedTarget
    if (!(next instanceof Element) || !event.currentTarget.contains(next)) setDragOver(null)
  }

  const handleRootDrop = (event: React.DragEvent<HTMLDivElement>) => {
    if (!dragBlock) return
    event.preventDefault()
    setDragBlock(null)
    setDragOver(null)
    setStatus('Блок не добавлен: перетащите карточку на поле схемы')
  }

  // --- Перестановка оборудования между контейнерами (E-2) -------------------
  const [relocate, setRelocate] = useState<{
    assetId: string
    name: string
    blockId: string | null
  } | null>(null)
  const [relocateError, setRelocateError] = useState<string | null>(null)
  const [relocateDanger, setRelocateDanger] = useState<string | null>(null)
  const [relocateBusy, setRelocateBusy] = useState(false)
  const [relocateReasons, setRelocateReasons] = useState<string[] | null>(null)
  const [pendingRelocateTarget, setPendingRelocateTarget] = useState<{ id: string | null } | null>(null)

  const handleMoveCell = useCallback((blockId: string, cellId: string, name: string) => {
    setRelocateError(null)
    setRelocateDanger(null)
    setRelocateReasons(null)
    setPendingRelocateTarget(null)
    setRelocate({ assetId: cellId, name, blockId })
  }, [])

  const openRelocateForNode = (assetId: string) => {
    const node = graph.nodes.find((item) => item.id === assetId)
    setRelocateError(null)
    setRelocateDanger(null)
    setRelocateReasons(null)
    setPendingRelocateTarget(null)
    setRelocate({ assetId, name: node?.name ?? assetId, blockId: null })
  }

  /** Точка на схеме для возврата объекта/ячейки из контейнера. */
  const relocateRootPoint = (): { x: number; y: number } => {
    const block = relocate?.blockId
      ? graph.blocks.find((item) => item.asset_id === relocate.blockId)
      : null
    const child = block?.children.find((item) => item.id === relocate?.assetId)
    if (block?.schema_x != null && child?.local_x != null) {
      return {
        x: block.schema_x + child.local_x,
        y: (block.schema_y ?? 0) + (child.local_y ?? 0),
      }
    }
    const rect = wrapperRef.current?.getBoundingClientRect()
    if (!rect) return { x: 240, y: 200 }
    return screenToFlowPosition({
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    })
  }

  const performRelocate = async (targetId: string | null, confirm: boolean) => {
    if (!relocate) return
    setRelocateBusy(true)
    setRelocateError(null)
    const point = relocateRootPoint()
    const base = {
      target_asset_id: targetId,
      ...(targetId === null ? { x: point.x, y: point.y } : {}),
      confirm,
    }
    try {
      const result = await gisApi.relocateAsset(relocate.assetId, base)
      const old = result
      pushCommand(
        `перенос «${relocate.name}»`,
        async () => {
          await gisApi.relocateAsset(relocate.assetId, {
            target_asset_id: old.old_block_id,
            confirm: true,
            x: old.old_schema_x ?? point.x,
            y: old.old_schema_y ?? point.y,
            local_x: old.old_local_x,
            local_y: old.old_local_y,
          })
        },
        async () => {
          await gisApi.relocateAsset(relocate.assetId, {
            ...base,
            confirm: true,
          })
        },
      )
      setStatus(
        result.warnings.length > 0
          ? `«${relocate.name}» перенесён. ${result.warnings.join(' ')} — камера наведена`
          : `«${relocate.name}» перенесён в новый контейнер — камера наведена`,
      )
      setRelocate(null)
      setRelocateDanger(null)
      setRelocateReasons(null)
      setPendingRelocateTarget(null)
      setDangerHint(null)
      onGraphChanged()
      focusAsset(targetId ?? relocate.assetId)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'schema.move.confirmation_required') {
        const reasons = Object.entries(err.fields)
          .filter(([key]) => key.startsWith('reason_'))
          .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
          .map(([, value]) => value)
        setRelocateReasons(reasons.length ? reasons : err.message.split('\n').filter(Boolean))
        setPendingRelocateTarget({ id: targetId })
      } else {
        const detail = err instanceof ApiError ? err.message : 'Не удалось перенести объект'
        setRelocateError(detail)
        if (err instanceof ApiError) {
          // Подсветка опасности + причина: напряжение, направление, границы, фидер и т.п.
          const reason = relocateDangerText(err)
          setRelocateDanger(reason)
          setDangerHint(reason)
        }
      }
    } finally {
      setRelocateBusy(false)
    }
  }

  // Флаги режимов и выделение нужны пересборке в момент её запуска, но не являются
  // её триггерами: их обновляет отдельный точечный эффект ниже.
  const modeRef = useRef<{ flags: NodeModeFlags; selectedId: string | null }>({
    flags: {
      editable: false,
      portDrag: false,
      draggable: false,
      jumperMode: false,
      jumperFirstId: null,
      linkCellsMode: false,
      cellLinkFirstId: null,
      cableMode: false,
      cableFromCellId: null,
      activeConnection: null,
    },
    selectedId: null,
  })
  const handlersRef = useRef({
    onSelect,
    onAddCell: handleAddCell,
    onAddCellsBulk: handleBulkCells,
    onDeleteCell: handleDeleteCell,
    onMoveCell: handleMoveCell,
    onToggleCollapse: handleToggleCollapse,
    onCellPick: handleCellPick,
    onCellLink: handleCellLink,
    onCellCable: handleCellCable,
    onPortMove,
  })

  const modeFlags = useMemo<NodeModeFlags>(
    () => ({
      editable: editMode && canEdit,
      portDrag: editMode && canEdit && portDrag,
      draggable: editMode && canEdit && !portDrag,
      jumperMode,
      jumperFirstId: jumperFirst?.cellId ?? null,
      linkCellsMode: cellLinkMode,
      cellLinkFirstId: cellLinkFirst?.cellId ?? null,
      cableMode,
      cableFromCellId: cableFrom?.cellId ?? null,
      activeConnection,
    }),
    [editMode, canEdit, portDrag, jumperMode, jumperFirst, cellLinkMode, cellLinkFirst, cableMode, cableFrom, activeConnection],
  )

  // Обновляем «последние» значения до эффектов пересборки (объявлен первым — выполнится первым).
  useEffect(() => {
    modeRef.current = { flags: modeFlags, selectedId }
    handlersRef.current = {
      onSelect,
      onAddCell: handleAddCell,
      onAddCellsBulk: handleBulkCells,
      onDeleteCell: handleDeleteCell,
    onMoveCell: handleMoveCell,
      onToggleCollapse: handleToggleCollapse,
      onCellPick: handleCellPick,
      onCellLink: handleCellLink,
      onCellCable: handleCellCable,
      onPortMove,
    }
  })

  // Полная сборка схемы только при смене графа: позиции из БД приоритетнее dagre
  useEffect(() => {
    const positions = nodePositions(graph)
    const flags = modeRef.current.flags
    const blockByAsset = new Map(graph.blocks.map((block) => [block.asset_id, block]))
    setNodes(
      graph.nodes.map((node) => ({
        id: node.id,
        type: 'asset',
        position: positions[node.id],
        selected: node.id === modeRef.current.selectedId,
        draggable: flags.draggable,
        data: {
          node,
          editable: flags.editable,
          portDrag: flags.portDrag,
          portPositions: portsForNode(node),
          onPortMove: (portId: string, x: number, y: number) =>
            handlersRef.current.onPortMove(node.id, portId, x, y),
          block: blockByAsset.get(node.id),
          onSelectChild: (id: string) => handlersRef.current.onSelect(id),
          onAddCell: (id: string) => handlersRef.current.onAddCell(id),
          onAddCellsBulk: (id: string) => handlersRef.current.onAddCellsBulk(id),
          onDeleteCell: (assetId: string, cellId: string, name: string) =>
            handlersRef.current.onDeleteCell(assetId, cellId, name),
          onMoveCell: (assetId: string, cellId: string, name: string) =>
            handlersRef.current.onMoveCell(assetId, cellId, name),
          onToggleCollapse: (assetId: string, collapsed: boolean) =>
            handlersRef.current.onToggleCollapse(assetId, collapsed),
          activeConnection: flags.activeConnection,
          jumperMode: flags.jumperMode,
          jumperFirstId: flags.jumperFirstId,
          onCellPick: (blockId: string, cellId: string, name: string) =>
            handlersRef.current.onCellPick(blockId, cellId, name),
          linkCellsMode: flags.linkCellsMode,
          onCellLink: (blockId: string, cellId: string, name: string) =>
            void handlersRef.current.onCellLink(blockId, cellId, name),
          cellLinkFirstId: flags.cellLinkFirstId,
          cableMode: flags.cableMode,
          onCellCable: (blockId: string, cellId: string, name: string) =>
            handlersRef.current.onCellCable(blockId, cellId, name),
          cableFromCellId: flags.cableFromCellId,
        },
      })),
    )
    setEdges(buildEdges(graph, positions))
    setDirty(false)
    setStatus(null)
    setError(null)
    setEdgeDraft(null)
    setPending(null)
    // Пересборка зависит только от графа: флаги режимов и выделение применяются точечно ниже.
  }, [graph, setNodes, setEdges])

  // Флаги режимов обновляются точечно: без dagre, без пересборки связей и замыканий.
  useEffect(() => {
    setNodes((current) => applyNodeModes(current, modeFlags))
  }, [modeFlags, setNodes])

  // Выделение — тоже точечно: меняются только бывший и новый выбранный узел.
  useEffect(() => {
    setNodes((current) => applySelection(current, selectedId))
  }, [selectedId, setNodes])

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

  const resolvePorts = (
    connection: Connection,
  ): { sourcePortId: string; targetPortId: string } | { error: string } => {
    const sourceNode = graph.nodes.find((node) => node.id === connection.source)
    const targetNode = graph.nodes.find((node) => node.id === connection.target)
    if (!sourceNode || !targetNode) return { error: 'Не найден объект связи' }

    const sourcePort =
      sourceNode.ports.find((port) => port.id === connection.sourceHandle) ??
      sourceNode.ports.find((port) => port.kind === 'out' || port.kind === 'io')
    const targetPort =
      targetNode.ports.find((port) => port.id === connection.targetHandle) ??
      targetNode.ports.find((port) => port.kind === 'in' || port.kind === 'io')

    if (!sourcePort) return { error: `У объекта «${sourceNode.name}» нет выходного порта` }
    if (!targetPort) return { error: `У объекта «${targetNode.name}» нет входного порта` }
    if (sourcePort.kind === 'in') return { error: 'Соединять можно только выход со входом (OUT → IN)' }
    if (targetPort.kind === 'out') return { error: 'Соединять можно только выход со входом (OUT → IN)' }

    const fromKv = sourcePort.nominal_voltage_kv
    const toKv = targetPort.nominal_voltage_kv
    if (fromKv != null && toKv != null && fromKv !== toKv) {
      return { error: `Напряжения не совпадают: ${fromKv} кВ и ${toKv} кВ` }
    }

    return { sourcePortId: sourcePort.id, targetPortId: targetPort.id }
  }

  const snapshotPositions = (): Record<string, XYPosition> =>
    Object.fromEntries(nodes.map((node) => [node.id, { ...node.position }]))

  const applyPositions = (positions: Record<string, XYPosition>) => {
    setNodes((current) =>
      current.map((node) => (positions[node.id] ? { ...node, position: positions[node.id] } : node)),
    )
    setDirty(true)
  }

  const runHistory = useCallback(
    async (direction: 'undo' | 'redo') => {
      const entry =
        direction === 'undo'
          ? historyRef.current[historyIndex.current - 1]
          : historyRef.current[historyIndex.current]
      if (!entry) return
      setError(null)

      if (entry.kind === 'positions') {
        applyPositions(direction === 'undo' ? entry.before : entry.after)
      } else {
        setSaving(true)
        try {
          await (direction === 'undo' ? entry.undo : entry.redo)()
          onGraphChanged()
          setStatus(`${entry.label}: ${direction === 'undo' ? 'отменено' : 'повторено'}`)
        } catch (err) {
          setError(err instanceof ApiError ? err.message : 'Не удалось отменить действие')
          return
        } finally {
          setSaving(false)
        }
      }

      historyIndex.current += direction === 'undo' ? -1 : 1
      setHistoryVersion((value) => value + 1)
    },
    [applyPositions, onGraphChanged],
  )

  const undo = () => void runHistory('undo')
  const redo = () => void runHistory('redo')

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!canEdit || !(event.ctrlKey || event.metaKey)) return
      // не перехватываем отмену там, где пользователь печатает текст
      const target = event.target as HTMLElement | null
      const tag = target?.tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || target?.isContentEditable) return
      const key = event.key.toLowerCase()
      if (key === 'z' && !event.shiftKey) {
        event.preventDefault()
        void runHistory('undo')
      } else if (key === 'y' || (key === 'z' && event.shiftKey)) {
        event.preventDefault()
        void runHistory('redo')
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [canEdit, runHistory])

  const downloadPassport = async (id: string) => {
    try {
      const result = await gisApi.passportUrl(id)
      window.open(result.url, '_blank')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сформировать паспорт')
    }
  }

  const createPoleLine = async (path: Array<{ x: number; y: number }>) => {
    setSaving(true)
    try {
      const result = await gisApi.generatePoles({
        type_code: 'op',
        x1: path[0].x,
        y1: path[0].y,
        x2: path[path.length - 1].x,
        y2: path[path.length - 1].y,
        count: Math.max(1, Number(poleForm.count) || 1),
        start: Number(poleForm.start) || 1,
        step: Math.max(1, Number(poleForm.step) || 1),
        prefix: poleForm.prefix || 'оп.',
        path: path.map((point) => [point.x, point.y]),
      })
      setStatus(`Создано опор: ${result.count} (${result.first}…${result.last})`)
      setPolePath([])
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось расставить опоры')
    } finally {
      setSaving(false)
    }
  }

  const finishPoleLine = () => {
    if (polePath.length < 2) {
      setError('Поставьте минимум две точки линии')
      return
    }
    void createPoleLine(polePath)
    setPolePick(null)
  }

  useEffect(() => {
    if (!polePick) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Enter') {
        event.preventDefault()
        finishPoleLine()
      }
      if (event.key === 'Escape') {
        setPolePick(null)
        setPolePath([])
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [polePick, polePath])

  const renumberChain = async () => {
    if (!poleAnchor) {
      setError('Сначала укажите опору на линии')
      return
    }
    setSaving(true)
    try {
      const result = await gisApi.renumberPolesChain({
        anchor_asset_id: poleAnchor.id,
        type_code: 'op',
        start: Number(poleForm.start) || 1,
        step: Math.max(1, Number(poleForm.step) || 1),
        prefix: poleForm.prefix || 'оп.',
      })
      setStatus(`Перенумерована линия: ${result.count} опор (${result.first}…${result.last})`)
      setPoleDialog(null)
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось перенумеровать линию')
    } finally {
      setSaving(false)
    }
  }

  const renumberAllPoles = async () => {
    if (!window.confirm('Перенумеровать ВСЕ опоры типа «Опора»? Имена существующих опор изменятся.')) return
    setSaving(true)
    try {
      const result = await gisApi.renumberPoles({
        type_code: 'op',
        start: Number(poleForm.start) || 1,
        step: Math.max(1, Number(poleForm.step) || 1),
        prefix: poleForm.prefix || 'оп.',
      })
      setStatus(`Перенумеровано: ${result.count} опор (${result.first}…${result.last})`)
      setPoleDialog(null)
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось перенумеровать опоры')
    } finally {
      setSaving(false)
    }
  }


  const handleCreatedOnSchema = (id: string, title: string) => {
    pushCommand(
      `создание «${title}»`,
      async () => {
        await gisApi.remove(id)
      },
      async () => {
        await gisApi.restoreAsset(id)
      },
    )
    onGraphChanged()
    focusAsset(id)
    setStatus(`Создано «${title}» — показано в центре схемы`)
  }

  const handlePlacedOnSchema = (
    id: string,
    x: number,
    y: number,
    previous: { x: number; y: number } | null,
  ) => {
    pushCommand(
      'постановка на схему',
      async () => {
        if (previous) {
          await gisApi.placeOnSchema(id, previous.x, previous.y)
        } else {
          await gisApi.unplaceFromSchema(id)
        }
      },
      async () => {
        await gisApi.placeOnSchema(id, x, y)
      },
    )
    onGraphChanged()
    focusAsset(id)
    setStatus('Объект из реестра поставлен на схему')
  }

  const addCenter = useCallback(() => {
    const rect = wrapperRef.current?.getBoundingClientRect()
    if (!rect) return { x: 240, y: 200 }
    return screenToFlowPosition({
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    })
  }, [screenToFlowPosition])

  const deleteNode = async (id: string) => {
    if (!window.confirm('Удалить объект со схемы? Карточка сохранится в реестре.')) return
    try {
      await gisApi.remove(id)
      pushCommand(
        'удаление объекта',
        async () => {
          await gisApi.restoreAsset(id)
        },
        async () => {
          await gisApi.remove(id)
        },
      )
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось удалить объект')
    }
  }

  const makeJumper = async (id: string) => {
    const previous = graph.edges.find((item) => item.id === id)?.link_type ?? 'cable'
    try {
      await gisApi.updateLink(id, { link_type: 'jumper' })
      pushCommand(
        'перемычка',
        async () => {
          await gisApi.updateLink(id, { link_type: previous })
        },
        async () => {
          await gisApi.updateLink(id, { link_type: 'jumper' })
        },
      )
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось изменить связь')
    }
  }

  const deleteEdge = async (id: string) => {
    if (!window.confirm('Удалить связь?')) return
    try {
      await gisApi.deleteLink(id)
      pushCommand(
        'удаление связи',
        async () => {
          await gisApi.restoreLink(id)
        },
        async () => {
          await gisApi.deleteLink(id)
        },
      )
      onGraphChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось удалить связь')
    }
  }

  const connect = async () => {
    if (!pending?.sourceHandle || !pending?.targetHandle) return
    setSaving(true)
    setError(null)
    try {
      const created = await gisApi.createLink({
        from_port_id: pending.sourceHandle,
        to_port_id: pending.targetHandle,
        link_type: linkType,
        cable_mark: cableMark.trim() || undefined,
      })
      let linkId = created.id
      pushCommand(
        'создание связи',
        async () => {
          await gisApi.deleteLink(linkId)
        },
        async () => {
          const again = await gisApi.restoreLink(linkId)
          linkId = again.id
        },
      )
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

  const openEdgeById = (id: string) => {
    if (!canEdit) return
    const source = graph.edges.find((item) => item.id === id)
    if (!source) return
    setEdgeDraft({
      id: source.id,
      label: source.label,
      cable_mark: source.cable_mark ?? '',
      length_m: source.length_m != null ? String(source.length_m) : '',
      state: source.state,
    })
  }

  const openEdge = (event: React.MouseEvent, edge: Edge) => {
    event.stopPropagation()
    openEdgeById(edge.id)
  }

  const saveEdge = async () => {
    if (!edgeDraft) return
    const previous = graph.edges.find((item) => item.id === edgeDraft.id)
    setSaving(true)
    setError(null)
    try {
      const nextCable = edgeDraft.cable_mark.trim() || null
      const nextLength = edgeDraft.length_m ? Number(edgeDraft.length_m.replace(',', '.')) : null
      await gisApi.updateLink(edgeDraft.id, {
        cable_mark: nextCable,
        length_m: nextLength,
        state: edgeDraft.state,
      })
      if (previous) {
        const before = {
          cable_mark: previous.cable_mark ?? null,
          length_m: previous.length_m ?? null,
          state: previous.state,
        }
        pushCommand(
          'правка связи',
          async () => {
            await gisApi.updateLink(edgeDraft.id, before)
          },
          async () => {
            await gisApi.updateLink(edgeDraft.id, {
              cable_mark: nextCable,
              length_m: nextLength,
              state: edgeDraft.state,
            })
          },
        )
      }
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
    const removedId = edgeDraft.id
    setSaving(true)
    try {
      await gisApi.deleteLink(removedId)
      pushCommand(
        'удаление связи',
        async () => {
          await gisApi.restoreLink(removedId)
        },
        async () => {
          await gisApi.deleteLink(removedId)
        },
      )
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
    <div
      ref={wrapperRef}
      className="relative h-full w-full"
      onDragOver={handleRootDragOver}
      onDragLeave={handleRootDragLeave}
      onDrop={handleRootDrop}
    >
      {canEdit && blocks.length > 0 ? (
        <div className="absolute left-2 top-16 z-10 max-h-[55%] w-[196px] overflow-y-auto rounded-xl border border-line bg-surface1/95 p-2 text-[12px] backdrop-blur">
          <div className="mb-1 text-[10px] uppercase tracking-wide text-ink3">Библиотека блоков</div>
          <div className="space-y-1">
            {blocks.map((block) => (
              <button
                key={block.id}
                type="button"
                draggable
                className="flex w-full cursor-grab items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] text-ink2 hover:bg-surface2 hover:text-ink active:cursor-grabbing"
                title={`${block.nodes_count} элементов · ${block.external_ports} внешних портов. Клик — поставить в центр, перетащите — в точку сброса`}
                onClick={() => void placeBlock(block.code)}
                onDragStart={(event) => startBlockDrag(event, block)}
                onDragEnd={finishBlockDrag}
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
          {/* Добавление и снимки доступны без режима редактирования: это не правка
              раскладки, и раньше кнопка терялась вместе с панелью инструментов */}
          <button
            type="button"
            className="btn-primary h-8 px-3"
            title="Добавить на схему объект из реестра, по типу или контуром"
            onClick={() => setAddOpen(true)}
          >
            + Добавить
          </button>
          <button
            type="button"
            className="btn-ghost h-8 px-2"
            title="Снимки схемы: зафиксировать состояние на дату, посмотреть и опубликовать"
            onClick={() => setSnapshotsOpen(true)}
          >
            Снимки
          </button>
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
                className={`btn-ghost h-8 px-3 ${cellLinkMode ? 'ring-1 ring-accent' : ''}`}
                title="Соединить ячейку одного комплекта с ячейкой другого"
                onClick={() => {
                  setJumperMode(false)
                  setPolePick(null)
                  setPolePath([])
                  setCellLinkFirst(null)
                  setCellLinkMode((value) => !value)
                }}
              >
                Ячейки
              </button>
              <button
                type="button"
                className={`btn-ghost h-8 px-3 ${cableMode ? 'ring-1 ring-accent' : ''}`}
                title="Кабель от ячейки к опоре или оборудованию линии"
                onClick={() => {
                  setJumperMode(false)
                  setCellLinkMode(false)
                  setCableFrom(null)
                  setCableMode((value) => !value)
                  setStatus(cableMode ? null : 'Кабель: кликните ячейку, затем опору или оборудование')
                }}
              >
                Кабель
              </button>
              <button type="button" className="btn-ghost h-8 px-2" title="Перенумеровать опоры" onClick={() => setPoleDialog('renumber')}>
                №
              </button>
              <button
                type="button"
                className="btn-ghost h-8 px-2"
                title="Отменить"
                disabled={historyIndex.current === 0}
                onClick={undo}
              >
                ↩
              </button>
              <button
                type="button"
                className="btn-ghost h-8 px-2"
                title="Повторить"
                disabled={historyIndex.current === historyRef.current.length}
                onClick={redo}
              >
                ↪
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
                  setPolePick(null)
                  setPolePath([])
                  setJumperMode(!jumperMode)
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

      <div
        data-schema-canvas
        className="absolute inset-0"
        onDragOver={handleCanvasDragOver}
        onDragLeave={handleCanvasDragLeave}
        onDrop={handleCanvasDrop}
      >
        <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={(_, node) => {
          if (cableMode && cableFrom) {
            if (node.id === cableFrom.blockId) {
              setError('Выберите другой объект: опору, КТП или разъединитель')
              return
            }
            void createCableTo(node.id)
            return
          }
          if (cellLinkMode) {
            void handleCellLink(node.id, '', node.data?.node?.name ?? node.id)
            return
          }
          if (anchorPick) {
            setPoleAnchor({ id: node.id, name: node.data?.node?.name ?? node.id })
            setAnchorPick(false)
            setStatus('Опора выбрана — нажмите «Перенумеровать линию»')
            return
          }
          onSelect(node.id)
        }}
        onEdgeClick={openEdge}
        onNodeDrag={(_, node) => {
          const width = node.measured?.width ?? 210
          const height = node.measured?.height ?? 84
          const cx = node.position.x + width / 2
          const cy = node.position.y + height / 2
          let guideX: number | undefined
          let guideY: number | undefined
          for (const other of nodes) {
            if (other.id === node.id) continue
            const ow = other.measured?.width ?? 210
            const oh = other.measured?.height ?? 84
            const ox = other.position.x + ow / 2
            const oy = other.position.y + oh / 2
            if (Math.abs(cx - ox) < 8) guideX = ox
            if (Math.abs(cy - oy) < 8) guideY = oy
          }
          setGuides(guideX != null || guideY != null ? { x: guideX, y: guideY } : null)
        }}
        onNodeDragStart={() => {
          dragStartPositions.current = snapshotPositions()
        }}
        onNodeDragStop={() => {
          const before = dragStartPositions.current
          const after = snapshotPositions()
          if (before) {
            pushHistory({ kind: 'positions', before, after })
          }
          dragStartPositions.current = null
          setGuides(null)
          setDirty(true)
        }}
        onNodeContextMenu={(event, node) => {
          event.preventDefault()
          setMenu({ x: event.clientX, y: event.clientY, type: 'node', id: node.id })
        }}
        onEdgeContextMenu={(event, edge) => {
          event.preventDefault()
          setMenu({ x: event.clientX, y: event.clientY, type: 'edge', id: edge.id })
        }}
        onPaneContextMenu={(event) => {
          event.preventDefault()
          setMenu({ x: event.clientX, y: event.clientY, type: 'pane' })
        }}
        onPaneClick={(event) => {
          setMenu(null)
          if (!polePick) return
          const point = screenToFlowPosition({ x: event.clientX, y: event.clientY })
          setPolePath((current) => [
            ...current,
            { x: Math.round(point.x), y: Math.round(point.y) },
          ])
          setStatus('Точка добавлена. Enter или «Завершить линию» — построить ВЛ')
        }}
        onConnectStart={(_, params) => {
          if (!editMode || portDrag) return
          const node = graph.nodes.find((item) => item.id === params.nodeId)
          if (!node) return
          const port = node.ports.find((item) => item.id === params.handleId)
          const sideKind = params.handleId?.endsWith('-out')
            ? 'out'
            : params.handleId?.endsWith('-in')
              ? 'in'
              : null
          setActiveConnection({
            nodeId: params.nodeId ?? '',
            portId: params.handleId ?? '',
            kind: port?.kind ?? sideKind ?? 'out',
            voltage: port?.nominal_voltage_kv ?? null,
          })
        }}
        onConnectEnd={() => setActiveConnection(null)}
        isValidConnection={(candidate) => {
          const connection = candidate as Connection
          if (!connection.source || !connection.target) return false
          if (connection.source === connection.target) return false
          const resolved = resolvePorts(connection)
          return !('error' in resolved)
        }}
        onConnect={(connection) => {
          if (!editMode || portDrag) return
          if (connection.source === connection.target) return
          const resolved = resolvePorts(connection)
          if ('error' in resolved) {
            setError(resolved.error)
            setPending(null)
            return
          }
          setPending({ ...connection, sourceHandle: resolved.sourcePortId, targetHandle: resolved.targetPortId })
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
        className="h-full w-full bg-[#070C10]"
      >
        <Background color="#1B2733" gap={GRID} size={1} />
        <ViewportPortal>
          {polePath.length > 1 ? (
            <svg style={{ position: 'absolute', left: 0, top: 0, overflow: 'visible', pointerEvents: 'none' }}>
              <polyline
                points={polePath.map((point) => `${point.x},${point.y}`).join(' ')}
                fill="none"
                stroke="#4C9AFF"
                strokeWidth={2}
                strokeDasharray="6 4"
              />
            </svg>
          ) : null}
          {guides?.x != null ? (
            <div
              style={{
                position: 'absolute',
                left: guides.x,
                top: -4000,
                height: 8000,
                borderLeft: '1px dashed #4C9AFF',
              }}
            />
          ) : null}
          {guides?.y != null ? (
            <div
              style={{
                position: 'absolute',
                top: guides.y,
                left: -4000,
                width: 8000,
                borderTop: '1px dashed #4C9AFF',
              }}
            />
          ) : null}
        </ViewportPortal>
        <Controls
          showInteractive={false}
          position="bottom-right"
          style={{ bottom: 'calc(var(--bottom-nav) + 12px)', right: 12 }}
        />
        </ReactFlow>
        {dragBlock ? (
          <div
            className={`pointer-events-none absolute inset-0 z-[6] ${
              dragOver === 'invalid'
                ? 'schema-danger ring-2 ring-inset ring-bad/70 bg-bad/5'
                : dragOver === 'canvas'
                  ? 'ring-2 ring-inset ring-accent bg-accent/10'
                  : 'ring-2 ring-inset ring-accent/40 bg-accent/[0.03]'
            }`}
          >
            {showDragHint ? (
              <div
                role="status"
                aria-live="polite"
                className={`schema-hint absolute inset-x-0 bottom-24 mx-auto w-fit max-w-[92%] rounded-full border px-3 py-1.5 text-[12px] shadow-lg backdrop-blur ${
                  dragOver === 'invalid'
                    ? 'border-bad/60 bg-[#2A1114]/95 text-bad'
                    : 'border-accent/50 bg-surface1/95 text-ink'
                }`}
              >
                {dragOver === 'invalid'
                  ? `Недопустимая зона: «${dragBlock.name}» встаёт только на поле схемы, не на панели и не на тулбар`
                  : dragOver === 'canvas'
                    ? `Отпустите — «${dragBlock.name}» встанет здесь, камера наведётся`
                    : `Перетащите «${dragBlock.name}» на поле схемы (подсказка скроется сама)`}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      {dangerHint ? (
        <div
          role="alert"
          aria-live="assertive"
          className="schema-hint schema-danger absolute left-1/2 top-14 z-[14] w-[min(92%,420px)] -translate-x-1/2 rounded-xl border border-bad/60 bg-[#2A1114]/95 px-3 py-2 text-[12px] text-bad shadow-xl"
        >
          ⚠ {dangerHint}
        </div>
      ) : null}

      {menu ? (
        <div
          className="fixed z-[1300] min-w-[180px] rounded-lg border border-line bg-surface1 p-1 text-[12px] shadow-xl"
          style={{ left: menu.x, top: menu.y }}
          onClick={(event) => event.stopPropagation()}
        >
          {menu.type === 'node' && menu.id ? (
            <>
              <button type="button" className="block w-full rounded px-2 py-1.5 text-left hover:bg-surface2" onClick={() => { onSelect(menu.id!); setMenu(null) }}>
                Открыть карточку
              </button>
              <button type="button" className="block w-full rounded px-2 py-1.5 text-left hover:bg-surface2" onClick={() => { void downloadPassport(menu.id!); setMenu(null) }}>
                ⬇ Скачать паспорт (PDF)
              </button>
              {canEdit && !graph.blocks.some((block) => block.asset_id === menu.id) ? (
                <button
                  type="button"
                  className="block w-full rounded px-2 py-1.5 text-left hover:bg-surface2"
                  onClick={() => {
                    openRelocateForNode(menu.id!)
                    setMenu(null)
                  }}
                >
                  ⇄ Перенести в блок/контур…
                </button>
              ) : null}
              {graph.blocks.some((block) => block.asset_id === menu.id) ? (
                <button
                  type="button"
                  className="block w-full rounded px-2 py-1.5 text-left hover:bg-surface2"
                  onClick={() => {
                    const block = graph.blocks.find((item) => item.asset_id === menu.id)
                    void handleToggleCollapse(menu.id!, !block?.collapsed)
                    setMenu(null)
                  }}
                >
                  Свернуть / развернуть
                </button>
              ) : null}
              <button type="button" className="block w-full rounded px-2 py-1.5 text-left text-bad hover:bg-surface2" onClick={() => { void deleteNode(menu.id!); setMenu(null) }}>
                Удалить
              </button>
            </>
          ) : null}
          {menu.type === 'edge' && menu.id ? (
            <>
              <button type="button" className="block w-full rounded px-2 py-1.5 text-left hover:bg-surface2" onClick={() => { openEdgeById(menu.id!); setMenu(null) }}>
                Редактировать связь
              </button>
              <button type="button" className="block w-full rounded px-2 py-1.5 text-left hover:bg-surface2" onClick={() => { void makeJumper(menu.id!); setMenu(null) }}>
                Сделать перемычкой
              </button>
              <button type="button" className="block w-full rounded px-2 py-1.5 text-left text-bad hover:bg-surface2" onClick={() => { void deleteEdge(menu.id!); setMenu(null) }}>
                Удалить
              </button>
            </>
          ) : null}
          {menu.type === 'pane' ? (
            <>
              <button type="button" className="block w-full rounded px-2 py-1.5 text-left hover:bg-surface2" onClick={() => { applyAuto(); setMenu(null) }}>
                Авто-раскладка
              </button>
              <button type="button" className="block w-full rounded px-2 py-1.5 text-left hover:bg-surface2" onClick={() => { undo(); setMenu(null) }}>
                Отменить
              </button>
              <button type="button" className="block w-full rounded px-2 py-1.5 text-left hover:bg-surface2" onClick={() => { redo(); setMenu(null) }}>
                Повторить
              </button>
            </>
          ) : null}
        </div>
      ) : null}

      <SnapshotsPanel
        open={snapshotsOpen}
        onClose={() => setSnapshotsOpen(false)}
        canPublish={canEdit}
      />

      <BulkCellsDialog
        open={Boolean(bulkParent)}
        parentId={bulkParent?.id ?? null}
        parentName={bulkParent?.name ?? ''}
        onClose={() => setBulkParent(null)}
        onCreated={handleBulkCreated}
      />

      <AddToSchemaPanel
        open={addOpen}
        onClose={() => setAddOpen(false)}
        center={addCenter()}
        onCreatedAsset={handleCreatedOnSchema}
        onPlaced={handlePlacedOnSchema}
        onLineEquipment={handleLineEquipment}
      />

      {poleDialog ? (
        <div className="fixed inset-0 z-[1400] flex items-end justify-center bg-black/60 p-3 sm:items-center">
          <div className="card modal-safe w-full max-w-md p-4 text-[13px]">
            <div className="mb-2 text-[15px] font-semibold">
              {poleDialog === 'generate' ? 'Расставить опоры ВЛ' : 'Перенумеровать опоры'}
            </div>
            {poleDialog === 'generate' ? (
              <p className="mb-3 text-[12px] text-ink3">
                Задайте количество и нумерацию, затем поставьте на схеме несколько точек —
                линия пойдёт по ним (как полилиния). Enter или кнопка «Завершить линию» —
                построить ВЛ. Опоры распределятся по всей длине, связи пойдут по сегментам.
              </p>
            ) : (
              <div className="mb-3 space-y-2 text-[12px] text-ink3">
                <label className="flex items-center gap-2 text-ink2">
                  <input type="radio" checked={renumberMode === 'chain'} onChange={() => setRenumberMode('chain')} />
                  только выбранная линия
                </label>
                <label className="flex items-center gap-2 text-ink2">
                  <input type="radio" checked={renumberMode === 'all'} onChange={() => setRenumberMode('all')} />
                  все опоры на схеме
                </label>
                {renumberMode === 'chain' ? (
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      className="btn-ghost h-8 px-2"
                      onClick={() => {
                        setPoleDialog(null)
                        setAnchorPick(true)
                        setStatus('Кликните опору на нужной линии')
                      }}
                    >
                      Указать опору
                    </button>
                    <span>{poleAnchor ? poleAnchor.name : 'опора не выбрана'}</span>
                  </div>
                ) : null}
              </div>
            )}
            <div className="mb-2 grid grid-cols-2 gap-2">
              {poleDialog === 'generate' ? (
                <label className="text-[11px] text-ink3">
                  Количество
                  <input className="input mt-1 h-8" inputMode="numeric" value={poleForm.count} onChange={(e) => setPoleForm({ ...poleForm, count: e.target.value })} />
                </label>
              ) : null}
              <label className="text-[11px] text-ink3">
                Начальный номер
                <input className="input mt-1 h-8" inputMode="numeric" value={poleForm.start} onChange={(e) => setPoleForm({ ...poleForm, start: e.target.value })} />
              </label>
              <label className="text-[11px] text-ink3">
                Шаг
                <input className="input mt-1 h-8" inputMode="numeric" value={poleForm.step} onChange={(e) => setPoleForm({ ...poleForm, step: e.target.value })} />
              </label>
              <label className="text-[11px] text-ink3">
                Префикс
                <input className="input mt-1 h-8" value={poleForm.prefix} onChange={(e) => setPoleForm({ ...poleForm, prefix: e.target.value })} />
              </label>
            </div>
            <div className="mt-3 flex gap-2">
              {poleDialog === 'generate' ? (
                <button
                  type="button"
                  className="btn-primary h-9 flex-1"
                  onClick={() => {
                    setPoleDialog(null)
                    setPolePath([])
                    setPolePick('polyline')
                    setStatus('Кликните точки линии ВЛ. Enter — завершить')
                  }}
                >
                  Указать точки
                </button>
              ) : (
                <button
                  type="button"
                  className="btn-primary h-9 flex-1"
                  disabled={saving || (renumberMode === 'chain' && !poleAnchor)}
                  onClick={() => (renumberMode === 'chain' ? void renumberChain() : void renumberAllPoles())}
                >
                  Перенумеровать
                </button>
              )}
              <button type="button" className="btn-ghost h-9" onClick={() => setPoleDialog(null)}>Отмена</button>
            </div>
          </div>
        </div>
      ) : null}

      {polePick === 'polyline' ? (
        <div className="absolute inset-x-3 bottom-16 z-[1350] flex items-center gap-2 rounded-xl border border-accent/50 bg-surface1 p-2 text-[12px] shadow-xl sm:left-1/2 sm:right-auto sm:w-[360px] sm:-translate-x-1/2">
          <span className="min-w-0 flex-1 text-ink2">Точек: {polePath.length}. Enter или кнопка справа.</span>
          <button type="button" className="btn-primary h-8 px-3" disabled={polePath.length < 2 || saving} onClick={finishPoleLine}>
            Завершить линию
          </button>
          <button type="button" className="btn-ghost h-8 px-2" onClick={() => { setPolePick(null); setPolePath([]) }}>
            ✕
          </button>
        </div>
      ) : null}

      {showLegend ? (
        <div className="absolute right-3 top-16 z-[12] max-h-[60%] w-[240px] overflow-y-auto rounded-xl border border-line bg-surface1/95 p-2 text-[11px] shadow-lg">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wide text-ink3">Легенда редактора</span>
            <button type="button" className="text-[11px] text-ink3" onClick={() => setShowLegend(false)}>✕</button>
          </div>
          <div className="mb-2 space-y-0.5 border-b border-line pb-2">
            <div className="text-[10px] uppercase tracking-wide text-ink3">Питание</div>
            <div className="flex items-center gap-2 text-ink2">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: POWER_COLOR.on }} />
              красный — под напряжением
            </div>
            <div className="flex items-center gap-2 text-ink2">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: POWER_COLOR.off }} />
              зелёный — отключено / обесточено
            </div>
            <div className="text-ink3">заземлено — символ ⏚ у порта</div>
          </div>
          <div className="mb-2 space-y-0.5 border-b border-line pb-2">
            <div className="text-[10px] uppercase tracking-wide text-ink3">Связи</div>
            <div className="text-ink2">
              <span style={{ color: POWER_COLOR.on }}>━━</span> сплошная — соединена, под напряжением
            </div>
            <div className="text-ink2">
              <span style={{ color: POWER_COLOR.off }}>┅┅</span> пунктир — разомкнута / отключена
            </div>
            <div className="text-ink2">
              <span className="tracking-[2px]">···</span> точки — перемычка между ячейками
            </div>
            <div className="text-ink2">стрелка → направление «выход → вход»</div>
            <div className="text-ink3">тонкая светлая — внутренняя связь блока</div>
          </div>
          <div className="mb-2 space-y-0.5 border-b border-line pb-2">
            <div className="text-[10px] uppercase tracking-wide text-ink3">Фидеры и линии</div>
            <div className="text-ink2">фидер — линия от источника к приёмнику</div>
            <div className="text-ink2">красная — под напряжением, зелёная — обесточена</div>
            <div className="text-ink3">опоры ВЛ, КТП и разъединители — узлы линии</div>
          </div>
          <div className="space-y-1">
            <div className="text-[10px] uppercase tracking-wide text-ink3">Обозначения ГОСТ</div>
            {legend.length > 0 ? (
              legend.map((item) => (
                <div key={item.symbol} className="flex items-center justify-between gap-2">
                  <span className="truncate">{item.title}</span>
                  <span className="text-ink3">{item.count}</span>
                </div>
              ))
            ) : (
              <div className="text-ink3">на схеме пока нет объектов</div>
            )}
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
            <button type="button" className="btn-danger h-9 px-3" disabled={saving} onClick={() => setConfirmRemoveEdge(true)}>
              Удалить
            </button>
            <button type="button" className="btn-ghost h-9 px-3" onClick={() => setEdgeDraft(null)}>
              ✕
            </button>
          </div>
        </div>
      ) : null}

      {relocate ? (
        <div className="fixed inset-0 z-[1500] flex items-end justify-center bg-black/60 p-3 sm:items-center">
          <div className="card modal-safe w-full max-w-lg p-4 text-[13px]">
            <div className="mb-1 text-[15px] font-semibold">Перенести «{relocate.name}»</div>
            <p className="mb-3 text-[12px] text-ink3">
              Связи и порты сохранятся. Выберите блок или контур — объект встанет в свободный слот.
            </p>
            {relocateDanger || relocateError ? (
              <div
                role="alert"
                className="schema-danger mb-3 rounded-lg border border-bad/60 bg-bad/10 px-3 py-2 text-[12px] text-bad"
              >
                <div className="font-semibold">⚠ {relocateDanger ?? 'Перенос отклонён'}</div>
                {relocateError ? <div className="mt-1 text-[11px] opacity-90">{relocateError}</div> : null}
                <div className="mt-1 text-[11px] opacity-80">
                  Выберите другой блок/контур или верните объект на схему.
                </div>
              </div>
            ) : null}
            <div className="max-h-[45vh] space-y-1 overflow-y-auto">
              {graph.blocks
                .filter(
                  (block) =>
                    block.asset_id !== relocate.blockId && block.asset_id !== relocate.assetId,
                )
                .map((block) => (
                  <button
                    key={block.asset_id}
                    type="button"
                    className="flex w-full items-center justify-between gap-2 rounded-lg border border-line px-2.5 py-2 text-left hover:bg-surface2 disabled:opacity-50"
                    disabled={relocateBusy}
                    onClick={() => void performRelocate(block.asset_id, false)}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] text-ink">
                        {block.kind === 'contour' ? 'Контур' : 'Блок'} · {block.name}
                      </span>
                      <span className="block text-[11px] text-ink3">
                        {block.code} · {block.children.length} элементов
                      </span>
                    </span>
                    <span className="shrink-0 text-[11px] text-accent">перенести →</span>
                  </button>
                ))}
              {relocate.blockId ? (
                <button
                  type="button"
                  className="flex w-full items-center justify-between gap-2 rounded-lg border border-dashed border-line px-2.5 py-2 text-left hover:bg-surface2 disabled:opacity-50"
                  disabled={relocateBusy}
                  onClick={() => void performRelocate(null, false)}
                >
                  <span className="text-[13px] text-ink">Без контейнера — вернуть на схему</span>
                  <span className="text-[11px] text-accent">на схему →</span>
                </button>
              ) : null}
              {graph.blocks.filter(
                (block) =>
                  block.asset_id !== relocate.blockId && block.asset_id !== relocate.assetId,
              ).length === 0 && !relocate.blockId ? (
                <p className="text-[12px] text-ink3">
                  На схеме нет блоков или контуров, куда можно перенести объект.
                </p>
              ) : null}
            </div>
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                className="btn-ghost h-9 px-3 text-[12px]"
                disabled={relocateBusy}
                onClick={() => setRelocate(null)}
              >
                Отмена
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={Boolean(relocateReasons)}
        title="Перенос изменит связи"
        message={
          <div className="space-y-1">
            {relocateReasons?.map((reason) => (
              <div key={reason}>• {reason}</div>
            ))}
            <div className="pt-1 text-ink3">Продолжить перенос?</div>
          </div>
        }
        confirmLabel="Всё равно перенести"
        busy={relocateBusy}
        onConfirm={() =>
          pendingRelocateTarget ? performRelocate(pendingRelocateTarget.id, true) : undefined
        }
        onCancel={() => setRelocateReasons(null)}
      />

      <ConfirmDialog
        open={confirmRemoveEdge && Boolean(edgeDraft)}
        title="Удалить связь?"
        message={edgeDraft ? `Связь «${edgeDraft.label}» исчезнет со схемы и с карты. Объекты и их история сохранятся.` : undefined}
        confirmLabel="Удалить"
        busy={saving}
        onConfirm={async () => {
          await removeEdge()
          setConfirmRemoveEdge(false)
        }}
        onCancel={() => setConfirmRemoveEdge(false)}
      />
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
