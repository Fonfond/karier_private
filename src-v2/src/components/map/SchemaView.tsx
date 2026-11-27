import { Fragment, memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  NodeResizer,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  useUpdateNodeInternals,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type XYPosition,
  ViewportPortal,
} from '@xyflow/react'
import dagre from 'dagre'
import '@xyflow/react/dist/style.css'
import type {
  AssetPort,
  CompositeCreateResult,
  GraphBlock,
  GraphBlockChild,
  GraphNode,
  SchemaLayoutItem,
  SchemaLayoutPortItem,
  TopologyGraph,
} from '../../lib/gis'
import {
  AUTOSAVE_DEBOUNCE_MS,
  AUTOSAVE_RETRY_MS,
  BLOCK_DEFAULT_WIDTH,
  BLOCK_MIN_HEIGHT,
  BLOCK_MIN_WIDTH,
  BLOCK_PADDING,
  CELL_GAP,
  CELL_MIN_WIDTH,
  LAYOUT_CHUNK_SIZE,
  blockLayoutItems,
  blockSizeOf,
  cellHandleId,
  cellWidthForBlock,
  chunkItems,
  clampCellBox,
  explicitCellLayout,
  nextSavePhase,
  parseCellHandle,
  saveIndicator,
  type CellLocal,
  type SavePhase,
} from '../../lib/schemaStage3'
import { downloadDxf } from '../../lib/dxf'
import { GostSymbol, SchemaFrameOverlay } from './GostSymbols'
import { SnapshotsPanel } from './SnapshotsPanel'
import { AddToSchemaPanel } from './AddToSchemaPanel'
import { BulkCellsDialog } from './BulkCellsDialog'
import { CompositeTemplateDialog } from './CompositeTemplateDialog'
import type { SchemaBlock, SchemaFrame } from '../../lib/gis'
import { POWER_COLOR, gisApi } from '../../lib/gis'
import { powerStateOf, powerSummary, toggleAriaLabel, voltageText } from '../../lib/power'
import { cellKindOf, cellKindTitle, cellNumberFromName, cellsLabel, elementsLabel } from '../../lib/equipmentTemplates'
import { ApiError } from '../../lib/api'
import { ConfirmDialog } from '../ui'

const NODE_W = 210
const NODE_H = 84
const GRID = 20

/** Оперативное состояние элемента блока (ячейки/разъединителя) на схеме. */
export interface CellPowerState {
  status: string
  grounded: boolean
  voltage_kv?: number | null
}

/** Этап 3: ячейка внутри блока — координаты относительно контента блока и её размер. */
type CellLayoutBox = { x: number; y: number; width: number; height: number }
type CellLayoutMap = Record<string, CellLayoutBox>

/** Снимок раскладки блока для автосейва: где стоят ячейки и каков контент блока. */
interface BlockCellsSnapshot {
  layout: CellLayoutMap
  bounds: { width: number; height: number }
}

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
  /** Этап 2: переключение ячеек/разъединителей (право `asset.status.edit`). */
  canSwitch?: boolean
  /** Статусы элементов блока: `children` графа не несут статус — подмешиваем из API. */
  cellStates?: Record<string, CellPowerState>
  onToggleCell?: (cellId: string, next: 'on' | 'off') => void
  onToggleNode?: (assetId: string, next: 'on' | 'off') => void
  /** Этап 3: ячейки измерились/подвинулись — блок отдаёт раскладку автосейву. */
  onCellsMeasured?: (blockId: string, layout: CellLayoutMap, bounds: { width: number; height: number }) => void
  onCellDragEnd?: (blockId: string, cellId: string, x: number, y: number) => void
  onBlockResizeEnd?: (blockId: string, width: number, height: number) => void
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

/**
 * Ячейки блока в порядке секций/номеров. F1: после перезагрузки графа порядок
 * children может измениться; для составных устройств (ПС/БКРУ/КТП) подписи секций
 * «прыгают» и разбивают блок. Legacy-блоки оставляем в исходном порядке.
 */
function sortedBlockCells(block: GraphBlock): GraphBlockChild[] {
  const rawCells = block.children.filter((child) => child.role !== 'busbar')
  const compositeCells = rawCells.some(
    (cell) => cell.params?.composite === true || cell.params?.cell_kind != null,
  )
  if (!compositeCells) return rawCells
  return rawCells
    .map((cell, index) => ({ cell, index }))
    .sort((a, b) => {
      const sectionA = Number(a.cell.params?.section_no ?? 0)
      const sectionB = Number(b.cell.params?.section_no ?? 0)
      if (sectionA !== sectionB) return sectionA - sectionB
      const numberA = cellNumberFromName(a.cell.name) ?? 0
      const numberB = cellNumberFromName(b.cell.name) ?? 0
      if (numberA !== numberB) return numberA - numberB
      return a.index - b.index
    })
    .map((item) => item.cell)
}


function AssetNodeImpl(props: NodeProps<Node<AssetNodeData>>) {
  const { data, selected, id: nodeId } = props
  const { node, editable, portDrag, portPositions, onPortMove } = data
  const blockBox = useRef<HTMLDivElement | null>(null)
  const cellRefs = useRef<Record<string, HTMLDivElement | null>>({})
  /** Контент блока: здесь лежат ячейки — он же «родитель» для ограничения перетаскивания. */
  const cellBodyRef = useRef<HTMLDivElement | null>(null)
  const [jumperLines, setJumperLines] = useState<
    { id: string; x1: number; y1: number; x2: number; y2: number; label: string | null }[]
  >([])
  /** Этап 3: живой размер блока — NodeResizer меняет его на каждом шаге перетаскивания. */
  const [liveSize, setLiveSize] = useState<{ width?: number; height?: number } | null>(null)
  /**
   * Ресайз перестраивает содержимое: ячейки раскладываются сеткой под новую ширину.
   * Ручные позиции (`draggedCells`) при этом сбрасываются — иначе после растяжения
   * блока весь текст оставался бы в узком столбце слева.
   */
  const [reflowLayout, setReflowLayout] = useState(false)
  /** Этап 3: измеренные позиции ячеек (px от левого верхнего угла контента блока). */
  const [measuredCells, setMeasuredCells] = useState<CellLayoutMap>({})
  /** Этап 3: позиции после перетаскивания — приоритетнее сохранённых в БД. */
  const [draggedCells, setDraggedCells] = useState<Record<string, CellLocal>>({})
  const [dragCellId, setDragCellId] = useState<string | null>(null)
  const [cellBodySize, setCellBodySize] = useState({ width: 0, height: 0 })
  const cellDrag = useRef<{
    cellId: string
    startX: number
    startY: number
    origin: CellLocal
    width: number
    height: number
    live: CellLocal
  } | null>(null)
  const updateNodeInternals = useUpdateNodeInternals()
  // под напряжением — красный, обесточено/отключено — зелёный
  const powerColor = node.energized || node.status === 'on' ? POWER_COLOR.on : POWER_COLOR.off
  const dim = !node.energized
  const nodePower = powerStateOf(node.status, node.grounded)
  // Разъединитель может стоять на схеме отдельным узлом (в КТП он внутри блока).
  const switchableNode = node.schema_symbol === 'disconnector' || node.type_code === 'razedinitel'
  const stateVoltage = nodePower.energized ? 'под напряжением' : 'обесточено'

  const block = data.block ?? null
  const collapsed = Boolean(block?.collapsed)
  const busbars = useMemo(
    () => (block ? block.children.filter((child) => child.role === 'busbar') : []),
    [block],
  )
  const cells = useMemo(() => (block ? sortedBlockCells(block) : []), [block])
  const savedLayout = useMemo(() => (block ? explicitCellLayout(block) : null), [block])
  const graphSize = useMemo(() => (block ? blockSizeOf(block) : null), [block])
  // Размер блока: живой ресайз → сохранённый в БД → дефолт. NodeProps.width для
  // этого не годится: React Flow отдаёт туда measured (0 до первого измерения),
  // из-за чего содержимое «схлопывалось» бы в 0 px.
  const size = liveSize ?? graphSize
  const blockWidth = size?.width != null && size.width > 0 ? size.width : BLOCK_DEFAULT_WIDTH
  const blockHeight = size?.height != null && size.height > 0 ? size.height : undefined
  // Граф перечитали (другое действие) — подхватываем сохранённый размер, но не
  // сбрасываем его во время самого ресайза: там liveSize свежее.
  useEffect(() => {
    setLiveSize(graphSize)
  }, [graphSize])
  // Новая версия блока из графа — сохранённая раскладка снова главная.
  useEffect(() => {
    setReflowLayout(false)
  }, [block])

  /** Базовая позиция ячейки: перетаскивание → БД → измеренная сетка. */
  const cellBaseline = (cellId: string) =>
    draggedCells[cellId] ??
    (reflowLayout ? measuredCells[cellId] : savedLayout?.[cellId] ?? measuredCells[cellId])

  const cellWidth = cellWidthForBlock(blockWidth)
  /** Итоговая раскладка ячеек: перетаскивание → БД → измеренная сетка. */
  const cellLayout = useMemo(() => {
    if (!block || collapsed || cells.length === 0) return null
    const bounds = {
      width: cellBodySize.width || Math.max(cellWidth, blockWidth - BLOCK_PADDING * 2),
      height: cellBodySize.height || 0,
    }
    const result: CellLayoutMap = {}
    for (const cell of cells) {
      const base = cellBaseline(cell.id)
      if (!base) return null
      const width = measuredCells[cell.id]?.width ?? cellWidth
      const height = measuredCells[cell.id]?.height ?? 0
      const clamped = bounds.height > 0 ? clampCellBox({ ...base, width, height }, bounds) : { x: base.x, y: base.y }
      result[cell.id] = { x: clamped.x, y: clamped.y, width, height }
    }
    return result
  }, [block, collapsed, cells, draggedCells, savedLayout, measuredCells, cellBodySize, cellWidth, blockWidth, reflowLayout])

  // Ячейки, которые ещё не имеют координат (блок без этапа 3 или новая ячейка),
  // измеряем по текущей сетке: так переход в режим редактирования не «дёргает» вёрстку.
  useLayoutEffect(() => {
    if (!block || collapsed || !editable || cells.length === 0) return
    if (cells.every((cell) => cellBaseline(cell.id))) return
    const body = cellBodyRef.current
    if (!body) return
    const next: CellLayoutMap = {}
    for (const cell of cells) {
      const element = cellRefs.current[cell.id]
      if (!element) continue
      next[cell.id] = {
        x: Math.round(element.offsetLeft),
        y: Math.round(element.offsetTop),
        width: Math.round(element.offsetWidth),
        height: Math.round(element.offsetHeight),
      }
    }
    if (Object.keys(next).length === 0) return
    setMeasuredCells((prev) => ({ ...prev, ...next }))
  }, [block, collapsed, editable, cells, draggedCells, savedLayout, measuredCells, reflowLayout])

  // Границы «родителя» для extent: размер контента блока (шапка и шины не в счёт).
  useLayoutEffect(() => {
    if (!block || collapsed) return
    const body = cellBodyRef.current
    if (!body) return
    const update = () => {
      const next = { width: body.clientWidth, height: body.clientHeight }
      setCellBodySize((prev) =>
        prev.width === next.width && prev.height === next.height ? prev : next,
      )
    }
    update()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(update)
    observer.observe(body)
    return () => observer.disconnect()
  }, [block, collapsed, cells.length, blockWidth, blockHeight])

  // Порты ячеек меняют положение вместе с раскладкой — React Flow должен
  // пересчитать границы handles, иначе линия к ячейке «отстаёт».
  useEffect(() => {
    if (!block) return
    updateNodeInternals(nodeId)
  }, [block, cellLayout, collapsed, nodeId, updateNodeInternals])

  // Снимок раскладки для автосейва: какие ячейки где и каков контент блока.
  useLayoutEffect(() => {
    if (!block || collapsed || !cellLayout) return
    data.onCellsMeasured?.(block.asset_id, cellLayout, {
      width: cellBodySize.width,
      height: cellBodySize.height,
    })
  }, [block, collapsed, cellLayout, cellBodySize, data])

  const startCellDrag = (cellId: string, event: React.PointerEvent<HTMLButtonElement>) => {
    const layout = cellLayout?.[cellId]
    if (!layout || !block) return
    event.stopPropagation()
    event.preventDefault()
    const element = cellRefs.current[cellId]
    cellDrag.current = {
      cellId,
      startX: event.clientX,
      startY: event.clientY,
      origin: { x: layout.x, y: layout.y },
      width: layout.width,
      height: layout.height || element?.offsetHeight || 44,
      live: { x: layout.x, y: layout.y },
    }
    event.currentTarget.setPointerCapture?.(event.pointerId)
    setDragCellId(cellId)
  }

  const moveCellDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    const drag = cellDrag.current
    if (!drag) return
    event.stopPropagation()
    const bounds = { width: cellBodySize.width, height: cellBodySize.height }
    if (!bounds.width || !bounds.height) return
    const next = clampCellBox(
      {
        x: drag.origin.x + (event.clientX - drag.startX),
        y: drag.origin.y + (event.clientY - drag.startY),
        width: drag.width,
        height: drag.height,
      },
      bounds,
    )
    drag.live = next
    setDraggedCells((prev) => ({ ...prev, [drag.cellId]: next }))
  }

  const stopCellDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    const drag = cellDrag.current
    if (!drag || !block) return
    event.stopPropagation()
    event.currentTarget.releasePointerCapture?.(event.pointerId)
    cellDrag.current = null
    setDragCellId(null)
    setDraggedCells((prev) => ({ ...prev, [drag.cellId]: drag.live }))
    data.onCellDragEnd?.(block.asset_id, drag.cellId, Math.round(drag.live.x), Math.round(drag.live.y))
  }


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


  if (block) {
    const jumperCells = new Set<string>()
    for (const jumper of block.jumpers ?? []) {
      jumperCells.add(jumper.from_cell_id)
      jumperCells.add(jumper.to_cell_id)
    }
    // Сводка по электробезопасности: включённые (красные) / обесточенные (зелёные).
    const blockPower = powerSummary(
      cells.map((cell) => ({
        status: data.cellStates?.[cell.id]?.status ?? 'off',
        grounded: data.cellStates?.[cell.id]?.grounded ?? false,
      })),
    )
    const roleColor = (role: string | null) => {
      if (role === 'incoming') return 'border-warm/50 text-warm'
      if (role === 'outgoing') return 'border-accent/50 text-accent'
      if (role === 'section') return 'border-[#C4A1FF]/50 text-[#C4A1FF]'
      return 'border-line text-ink2'
    }
    // Свободная раскладка: позиции ячеек известны (БД этапа 3 или измеренная сетка).
    // Иначе — привычная сетка, которая перестраивается при ресайзе.
    const freeform = cellLayout != null
    const sectionLabels = Array.from(
      new Set(
        cells
          .map((cell) => (cell.params?.section as string | undefined) ?? null)
          .filter((label): label is string => Boolean(label)),
      ),
    )
    const freeformHeight =
      freeform && cellLayout
        ? Math.max(40, ...Object.values(cellLayout).map((box) => box.y + (box.height || 44))) + 8
        : undefined

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
              <div className="text-[10px] text-ink3">{elementsLabel(cells.length + busbars.length)}</div>
              {cells.length > 0 ? (
                <div className="truncate text-[10px]" style={{ color: blockPower.energized > 0 ? POWER_COLOR.on : POWER_COLOR.off }}>
                  {blockPower.energized > 0 ? '⚡' : '○'} {blockPower.text}
                </div>
              ) : null}
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
        data-testid={`schema-block-${block.asset_id}`}
        data-block-width={Math.round(blockWidth)}
        data-block-height={blockHeight != null ? Math.round(blockHeight) : undefined}
        data-block-layout={freeform ? 'freeform' : 'grid'}
        className={`relative flex flex-col rounded-xl border-2 ${
          block.kind === 'contour'
            ? 'border-dashed border-accent/35 bg-surface1/70'
            : 'border-accent/45 bg-surface1/95'
        } ${selected ? 'ring-2 ring-accent' : ''}`}
        style={{ width: blockWidth, height: blockHeight ?? undefined }}
      >
        {/* Этап 3: угловые маркеры ресайза — встроенный NodeResizer из @xyflow/react 12. */}
        {editable ? (
          <NodeResizer
            nodeId={nodeId}
            isVisible
            minWidth={BLOCK_MIN_WIDTH}
            minHeight={BLOCK_MIN_HEIGHT}
            maxWidth={4000}
            maxHeight={4000}
            onResize={(_, params) =>
              setLiveSize({ width: Math.round(params.width), height: Math.round(params.height) })
            }
            onResizeEnd={(_, params) => {
              setLiveSize({ width: Math.round(params.width), height: Math.round(params.height) })
              // Содержимое перестраивается под новый размер: ячейки снова
              // раскладываются сеткой, а не остаются в старом узком столбце.
              setDraggedCells({})
              setMeasuredCells({})
              setReflowLayout(true)
              data.onBlockResizeEnd?.(block.asset_id, Math.round(params.width), Math.round(params.height))
            }}
            lineClassName="!border-accent/70"
            handleClassName="!h-2.5 !w-2.5 !rounded-sm !border !border-surface1 !bg-accent"
          />
        ) : null}
        <div className="flex shrink-0 items-start justify-between gap-2 border-b border-line px-2.5 py-2">
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold leading-tight text-ink">{block.name}</div>
            <div className="mt-0.5 text-[10px] text-ink3">
              {cellsLabel(cells.length)} · {busbars.length} шин
            </div>
            {cells.length > 0 ? (
              <div
                className="mt-0.5 truncate text-[10px]"
                style={{ color: blockPower.energized > 0 ? POWER_COLOR.on : POWER_COLOR.off }}
                title={`Электробезопасность: ${blockPower.text}`}
              >
                {blockPower.energized > 0 ? '⚡' : '○'} {blockPower.text}
              </div>
            ) : null}
            {freeform && sectionLabels.length > 0 ? (
              <div
                className="mt-0.5 truncate text-[9px] text-ink3"
                title={`Секции: ${sectionLabels.join(', ')}`}
              >
                Секции: {sectionLabels.join(' · ')}
              </div>
            ) : null}
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

        <div className="shrink-0 space-y-2 px-2.5 py-2">
          {busbars.map((bus) => (
            <div key={bus.id}>
              <div className="text-[9px] uppercase tracking-wide text-ink3">{bus.name}</div>
              <div className="mt-0.5 h-[3px] w-full rounded bg-accent/70" />
            </div>
          ))}
        </div>

        {/* Контент блока: в обычном режиме — адаптивная сетка, в свободной
            раскладке — ячейки по сохранённым координатам (и перетаскивание внутри). */}
        <div className={`min-w-0 px-2.5 pb-2 ${blockHeight != null ? 'min-h-0 flex-1 overflow-auto' : ''}`}>
          <div
            ref={cellBodyRef}
            data-testid={`schema-block-body-${block.asset_id}`}
            className={`relative ${freeform ? '' : 'grid'}`}
            style={
              freeform
                ? { minHeight: freeformHeight }
                : { display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${CELL_MIN_WIDTH}px, 1fr))`, gap: CELL_GAP }
            }
          >
          {cells.map((cell, cellIndex) => {
            const section = (cell.params?.section as string | undefined) ?? null
            const previousSection =
              cellIndex > 0 ? ((cells[cellIndex - 1].params?.section as string | undefined) ?? null) : null
            const showSection = !freeform && Boolean(section) && section !== previousSection
            const sectionVoltage = cell.params?.voltage_kv
            // Этап 3: позиция ячейки внутри блока (перетаскивание/БД/измерение).
            const box = freeform ? cellLayout?.[cell.id] : undefined
            // Этап 2: вид ячейки (вводная/отходящая/секционная), её номер и питание
            const kind = cellKindOf(cell.params, cell.role)
            const number = cellNumberFromName(cell.name)
            const state = data.cellStates?.[cell.id]
            const power = powerStateOf(state?.status ?? 'off', state?.grounded ?? false)
            const isDisconnector = cell.params?.disconnector === true
            const kindColor =
              kind === 'in' ? '#F5A524' : kind === 'out' ? '#4C9AFF' : kind === 'sectional' ? '#C4A1FF' : undefined
            const nextState: 'on' | 'off' = power.energized ? 'off' : 'on'
            return (
            <Fragment key={cell.id}>
              {showSection ? (
                <div className="col-span-full mt-1 flex items-center gap-2 text-[9px] uppercase tracking-wide text-ink3">
                  <span className="h-px flex-1 bg-line" />
                  <span className="whitespace-nowrap">
                    {section}
                    {sectionVoltage != null ? ` · ${sectionVoltage} кВ` : ''}
                  </span>
                  <span className="h-px flex-1 bg-line" />
                </div>
              ) : null}
            <div
              key={cell.id}
              ref={(el) => { cellRefs.current[cell.id] = el }}
              data-cell-id={cell.id}
              data-cell-kind={kind ?? undefined}
              data-cell-number={number ?? undefined}
              data-power={power.kind}
              className={`group relative flex items-start gap-1 rounded-md border border-line bg-surface2/40 px-1.5 py-1 ${roleColor(
                cell.role,
              )} ${data.jumperFirstId === cell.id ? 'ring-2 ring-accent' : ''} ${
                dragCellId === cell.id ? 'z-[6] shadow-lg ring-2 ring-accent' : ''
              }`}
              style={{
                borderLeft: `3px solid ${power.color}`,
                ...(box
                  ? { position: 'absolute', left: box.x, top: box.y, width: box.width }
                  : undefined),
              }}
              title={`${cell.name}${kind ? ` · ${cellKindTitle(kind)}` : ''} — ${power.title}`}
            >
              {/* Этап 3: у ячейки свои порты — линию можно вести прямо к ней. */}
              <Handle
                id={cellHandleId(cell.id, 'in')}
                type="target"
                position={Position.Left}
                isConnectable={editable && !portDrag}
                className={`schema-cell-handle ${editable ? 'schema-cell-handle--edit' : ''}`}
                title={`Ввод ячейки «${cell.name}» — сюда приходит линия`}
              />
              <Handle
                id={cellHandleId(cell.id, 'out')}
                type="source"
                position={Position.Right}
                isConnectable={editable && !portDrag}
                className={`schema-cell-handle ${editable ? 'schema-cell-handle--edit' : ''}`}
                title={`Выход ячейки «${cell.name}» — отсюда идёт линия`}
              />
              {editable ? (
                <button
                  type="button"
                  className="nodrag absolute bottom-0.5 right-0.5 z-[3] grid h-3.5 w-3.5 cursor-move touch-none place-items-center rounded border border-accent/50 bg-surface1/85 text-[8px] leading-none text-accent hover:bg-accent/15"
                  data-testid={`cell-drag-${cell.id}`}
                  title="Перетащить ячейку внутри блока (за рамки блока не выйдет)"
                  aria-label={`Перетащить ячейку «${cell.name}» внутри блока`}
                  onPointerDown={(event) => startCellDrag(cell.id, event)}
                  onPointerMove={moveCellDrag}
                  onPointerUp={stopCellDrag}
                  onPointerCancel={stopCellDrag}
                  onClick={(event) => event.stopPropagation()}
                >
                  ⠿
                </button>
              ) : null}
              <button
                type="button"
                className="min-w-0 flex-1 text-left"
                title={`${cell.name} · ${cell.type_name ?? ''} — ${power.title}`}
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
                <div className="flex items-center gap-1">
                  {number != null ? (
                    <span className="rounded bg-surface1 px-1 font-mono text-[8px] text-ink2">№{number}</span>
                  ) : null}
                  {kind ? (
                    <span
                      className="truncate text-[8px] uppercase tracking-wide"
                      style={kindColor ? { color: kindColor } : undefined}
                    >
                      {isDisconnector ? 'разъединитель' : cellKindTitle(kind)}
                    </span>
                  ) : null}
                </div>
                <div className="truncate text-[10px] leading-tight">{cell.name}</div>
                {typeof cell.params?.cable === 'string' ? (
                  <div className="truncate text-[8px] text-ink3">{cell.params.cable}</div>
                ) : null}
                <div
                  className="mt-0.5 flex items-center gap-1 text-[8px]"
                  style={{ color: power.color }}
                  aria-label={`Состояние: ${power.label}`}
                >
                  <span aria-hidden="true">{power.icon}</span>
                  <span className="truncate">{power.label}</span>
                </div>
                {jumperCells.has(cell.id) ? (
                  <div className="mt-0.5 inline-flex items-center gap-0.5 rounded bg-[#C4A1FF]/20 px-1 text-[8px] text-[#C4A1FF]">
                    ⇄ перемычка
                  </div>
                ) : null}
              </button>
              {data.canSwitch && data.onToggleCell ? (
                <button
                  type="button"
                  data-testid={`toggle-cell-${cell.id}`}
                  className="mt-0.5 h-5 shrink-0 rounded border px-1 text-[9px] font-semibold"
                  style={{
                    color: power.energized ? POWER_COLOR.off : POWER_COLOR.on,
                    borderColor: power.energized ? POWER_COLOR.off : POWER_COLOR.on,
                  }}
                  title={
                    nextState === 'on'
                      ? `Включить «${cell.name}» — появится напряжение`
                      : `Отключить «${cell.name}» — объект будет обесточен`
                  }
                  aria-label={toggleAriaLabel(nextState, cell.name, power)}
                  onClick={(event) => {
                    event.stopPropagation()
                    data.onToggleCell?.(cell.id, nextState)
                  }}
                >
                  {power.energized ? 'Откл' : 'Вкл'}
                </button>
              ) : null}
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
        <span style={{ color: powerColor }}>{nodePower.icon}</span>
        <span className="text-ink2" style={{ color: powerColor }}>
          {powerStateOf(node.status, node.grounded).label}
        </span>
        {node.grounded ? <span className="text-ground">⏚</span> : null}
        {node.is_source ? <span className="ml-auto text-warm">источник</span> : null}
      </div>

      {switchableNode && data.canSwitch && data.onToggleNode ? (
        <button
          type="button"
          data-testid={`toggle-node-${node.id}`}
          className="mt-1 h-6 w-full rounded border text-[10px] font-semibold"
          style={{
            color: powerColor === POWER_COLOR.on ? POWER_COLOR.off : POWER_COLOR.on,
            borderColor: powerColor === POWER_COLOR.on ? POWER_COLOR.off : POWER_COLOR.on,
          }}
          title={
            powerColor === POWER_COLOR.on
              ? `Отключить «${node.name}» — объект будет обесточен`
              : `Включить «${node.name}» — появится напряжение`
          }
          aria-label={toggleAriaLabel(
            powerColor === POWER_COLOR.on ? 'off' : 'on',
            node.name,
            powerStateOf(node.status, node.grounded),
          )}
          onClick={(event) => {
            event.stopPropagation()
            data.onToggleNode?.(node.id, powerColor === POWER_COLOR.on ? 'off' : 'on')
          }}
        >
          {powerColor === POWER_COLOR.on ? 'Отключить' : 'Включить'}
          {stateVoltage ? ` · ${stateVoltage}` : ''}
        </button>
      ) : null}

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
    a.canSwitch === b.canSwitch &&
    a.cellStates === b.cellStates &&
    a.onToggleCell === b.onToggleCell &&
    a.onToggleNode === b.onToggleNode &&
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
    a.onCellCable === b.onCellCable &&
    a.onCellsMeasured === b.onCellsMeasured &&
    a.onCellDragEnd === b.onCellDragEnd &&
    a.onBlockResizeEnd === b.onBlockResizeEnd
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

/** Ячейка → её блок. По этой карте линия к ячейке рисуется к порту внутри блока. */
export function cellBlockMap(
  graph: TopologyGraph,
): Record<string, { blockId: string; collapsed: boolean }> {
  const result: Record<string, { blockId: string; collapsed: boolean }> = {}
  for (const block of graph.blocks) {
    for (const child of block.children) {
      result[child.id] = { blockId: block.asset_id, collapsed: Boolean(block.collapsed) }
    }
  }
  return result
}

type EdgeEndpoint = { nodeId: string; cellId?: string }

/**
 * Связи для React Flow. Этап 3: связь с ячейкой внутри блока рисуется к её порту
 * (handle `cell:<id>:in|out`) на узле блока — иначе линия «висела» бы в пустоте,
 * ведь ячейки не являются отдельными узлами холста. Перемычки внутри блока
 * не дублируем: они рисуются SVG-линиями внутри блока.
 */
export function buildEdges(graph: TopologyGraph, positions: Record<string, XYPosition>): Edge[] {
  const owners = cellBlockMap(graph)
  const endpoint = (assetId: string): EdgeEndpoint | null => {
    if (positions[assetId]) return { nodeId: assetId }
    const owner = owners[assetId]
    if (owner && !owner.collapsed) return { nodeId: owner.blockId, cellId: assetId }
    return null
  }
  const edges: Edge[] = []
  for (const edge of graph.edges) {
    if (edge.link_type === 'jumper') continue
    const source = endpoint(edge.from_asset_id)
    const target = endpoint(edge.to_asset_id)
    if (!source || !target) continue
    // Блок и его собственная ячейка (или две ячейки одного блока) — петля:
    // такие связи показывает карточка/перемычки, на холст их не выносим.
    if (source.nodeId === target.nodeId) continue
    const from = positions[source.nodeId]
    const to = positions[target.nodeId]
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
    // Порт ячейки важнее направления узла: линия должна прийти ровно в ячейку.
    if (source.cellId) sourceHandle = cellHandleId(source.cellId, 'out')
    if (target.cellId) targetHandle = cellHandleId(target.cellId, 'in')
    const open = edge.state !== 'connected'
    const jumper = edge.link_type === 'jumper'
    edges.push({
      id: edge.id,
      type: 'smoothstep',
      sourceHandle,
      targetHandle,
      source: source.nodeId,
      target: target.nodeId,
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
    })
  }
  return edges
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
  canSwitch,
  assetStates,
  onGraphChanged,
}: {
  graph: TopologyGraph
  selectedId: string | null
  onSelect: (id: string) => void
  canEdit: boolean
  canSwitch: boolean
  /** Статусы объектов из реестра (MapPage уже загрузил все объекты). */
  assetStates: Record<string, CellPowerState>
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
  const [templateOpen, setTemplateOpen] = useState(false)
  /**
   * Локальные состояния после переключения. Базовые статусы приходят из реестра
   * (`assetStates`): `GET /api/assets` уже загружен MapPage, поэтому на блок не
   * нужно по запросу на каждого ребёнка — иначе 500 запросов на схему.
   */
  const [cellStates, setCellStates] = useState<Record<string, CellPowerState>>({})
  const toggleBusyRef = useRef<Set<string>>(new Set())
  const mergedCellStates = useMemo(
    () => ({ ...assetStates, ...cellStates }),
    [assetStates, cellStates],
  )
  const [bulkParent, setBulkParent] = useState<{ id: string; name: string } | null>(null)
  const [cableMode, setCableMode] = useState(false)
  const [cableFrom, setCableFrom] = useState<{ cellId: string; name: string; blockId: string } | null>(null)
  const [chainMode, setChainMode] = useState(false)
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

  // --- этап 3: автосейв раскладки -------------------------------------------
  // Что сохранять: перемещённые узлы (x/y), размеры блоков (width/height) и
  // локальные координаты ячеек (local_x/local_y). Данные копятся в ref-наборах,
  // затем debounce 2 с отправляет только изменённое (put идемпотентен).
  const nodesRef = useRef<Node<AssetNodeData>[]>([])
  useEffect(() => {
    nodesRef.current = nodes
  }, [nodes])
  /** Размеры, полученные от NodeResizer — чтобы не потерять их до ответа сервера. */
  const savedBlockSizesRef = useRef<Record<string, { width: number; height: number }>>({})
  /** Снимки раскладки блоков из узлов (ячейки + границы контента). */
  const blockCellsRef = useRef<Record<string, BlockCellsSnapshot>>({})
  /** Позиции ячеек после перетаскивания (приоритетнее БД до перезагрузки графа). */
  const cellOverridesRef = useRef<Record<string, CellLocal>>({})
  const pendingRef = useRef<{ nodes: Set<string>; blocks: Set<string>; all: boolean }>({
    nodes: new Set<string>(),
    blocks: new Set<string>(),
    all: false,
  })
  const [savePhase, setSavePhase] = useState<SavePhase>('idle')
  const saveTimerRef = useRef<number | null>(null)
  const retryTimerRef = useRef<number | null>(null)
  const saveBusyRef = useRef(false)
  const pendingSaveRef = useRef(false)
  const flushSaveRef = useRef<(manual?: boolean) => Promise<void>>(() => Promise.resolve())

  const collectPortItems = (): SchemaLayoutPortItem[] =>
    nodesRef.current.flatMap((node) =>
      node.data.node.ports.map((port) => {
        const point = node.data.portPositions[port.id]
        return {
          port_id: port.id,
          x: Math.round((point?.x ?? 0.5) * 1000) / 1000,
          y: Math.round((point?.y ?? 0.5) * 1000) / 1000,
        }
      }),
    )

  const buildNodeItems = (): SchemaLayoutItem[] => {
    const pending = pendingRef.current
    const ids = pending.all
      ? nodesRef.current.map((node) => node.id)
      : Array.from(pending.nodes)
    const items: SchemaLayoutItem[] = []
    for (const id of ids) {
      if (pending.blocks.has(id)) continue
      const node = nodesRef.current.find((item) => item.id === id)
      if (!node) continue
      items.push({ asset_id: id, x: Math.round(node.position.x), y: Math.round(node.position.y) })
    }
    return items
  }

  /** Блок + его ячейки одним пакетом: размер, позиция и local_x/local_y ячеек. */
  const buildStage3Items = (): SchemaLayoutItem[] => {
    const items: SchemaLayoutItem[] = []
    for (const blockId of pendingRef.current.blocks) {
      const node = nodesRef.current.find((item) => item.id === blockId)
      const blockData = node?.data.block
      if (!node || !blockData) continue
      const width = Math.round(
        node.width ?? node.measured?.width ?? savedBlockSizesRef.current[blockId]?.width ?? 0,
      )
      const height = Math.round(
        node.height ?? node.measured?.height ?? savedBlockSizesRef.current[blockId]?.height ?? 0,
      )
      const snapshot = blockCellsRef.current[blockId]
      const cells = blockData.children.filter((child) => child.role !== 'busbar')
      const cellEntries: Array<{ id: string; local: CellLocal }> = []
      for (const cell of cells) {
        const override = cellOverridesRef.current[cell.id]
        const measured = snapshot?.layout[cell.id]
        const base =
          override ??
          measured ??
          (cell.local_x != null && cell.local_y != null
            ? { x: cell.local_x, y: cell.local_y }
            : null)
        if (!base) continue
        const bounds = snapshot
          ? snapshot.bounds
          : { width: Math.max(0, width - BLOCK_PADDING * 2), height: Math.max(0, height - 60) }
        if (!bounds.width || !bounds.height) continue
        // Вписываем в текущие рамки блока: после уменьшения блока старые
        // координаты иначе дали бы 422 out_of_bounds.
        cellEntries.push({
          id: cell.id,
          local: clampCellBox(
            {
              x: base.x,
              y: base.y,
              width: measured?.width ?? cellWidthForBlock(width || BLOCK_DEFAULT_WIDTH),
              height: measured?.height ?? 0,
            },
            bounds,
          ),
        })
      }
      items.push(
        ...blockLayoutItems({
          assetId: blockId,
          position: node.position,
          size: width > 0 && height > 0 ? { width, height } : null,
          cells: cellEntries,
        }),
      )
    }
    return items
  }

  /** Единая точка сохранения: и ручная кнопка, и автосейв идут сюда. */
  const flushSave = async (manual = false): Promise<void> => {
    if (!canEdit) return
    if (saveBusyRef.current) {
      pendingSaveRef.current = true
      return
    }
    if (saveTimerRef.current != null) {
      window.clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
    if (retryTimerRef.current != null) {
      window.clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
    const pending = pendingRef.current
    const nodeIdsSaved = pending.all
      ? nodesRef.current.map((node) => node.id)
      : Array.from(pending.nodes)
    const blockIdsSaved = Array.from(pending.blocks)
    const stage3Items = buildStage3Items()
    const stage3Ids = new Set(stage3Items.map((item) => item.asset_id))
    const items = [
      ...buildNodeItems().filter((item) => !stage3Ids.has(item.asset_id)),
      ...stage3Items,
    ]
    const ports = manual ? collectPortItems() : []
    if (items.length === 0 && ports.length === 0) {
      if (manual) setStatus('Изменений для сохранения нет')
      return
    }
    saveBusyRef.current = true
    setSavePhase('saving')
    try {
      let updated = 0
      let updatedPorts = 0
      let updatedBlocks = 0
      let updatedCells = 0
      const chunks = items.length > 0 ? chunkItems(items, LAYOUT_CHUNK_SIZE) : [[]]
      for (let index = 0; index < chunks.length; index += 1) {
        const result = await gisApi.saveSchemaLayout(chunks[index], index === 0 ? ports : [])
        updated += result.updated
        updatedPorts += result.updated_ports ?? 0
        updatedBlocks += result.updated_blocks ?? 0
        updatedCells += result.updated_cells ?? 0
      }
      for (const id of nodeIdsSaved) pendingRef.current.nodes.delete(id)
      for (const id of blockIdsSaved) pendingRef.current.blocks.delete(id)
      pendingRef.current.all = false
      setSavePhase('saved')
      setDirty(false)
      setError(null)
      if (manual) {
        const portsPart = ports.length > 0 ? `, портов ${updatedPorts}` : ''
        setStatus(
          `Сохранено: узлов ${updated}, блоков ${updatedBlocks}, ячеек ${updatedCells}${portsPart}`,
        )
      }
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Не удалось сохранить раскладку'
      setSavePhase('error')
      if (manual) setError(message)
      retryTimerRef.current = window.setTimeout(() => {
        retryTimerRef.current = null
        void flushSaveRef.current(false)
      }, AUTOSAVE_RETRY_MS)
    } finally {
      saveBusyRef.current = false
      if (pendingSaveRef.current) {
        pendingSaveRef.current = false
        scheduleAutosave()
      }
    }
  }
  flushSaveRef.current = flushSave

  /** Изменения пришли: через 2 с уйдёт PUT /api/topology/layout (ошибка — повтор через 5 с). */
  const scheduleAutosave = useCallback((delay: number = AUTOSAVE_DEBOUNCE_MS) => {
    if (saveBusyRef.current) {
      pendingSaveRef.current = true
      return
    }
    setSavePhase((phase) => nextSavePhase(phase, 'schedule'))
    if (saveTimerRef.current != null) window.clearTimeout(saveTimerRef.current)
    saveTimerRef.current = window.setTimeout(() => {
      saveTimerRef.current = null
      void flushSaveRef.current(false)
    }, delay)
  }, [])

  const handleCellsMeasured = useCallback(
    (blockId: string, layout: CellLayoutMap, bounds: { width: number; height: number }) => {
      blockCellsRef.current[blockId] = { layout, bounds }
    },
    [],
  )

  const handleCellDragEnd = useCallback(
    (blockId: string, cellId: string, x: number, y: number) => {
      cellOverridesRef.current[cellId] = { x, y }
      pendingRef.current.blocks.add(blockId)
      setDirty(true)
      scheduleAutosave()
    },
    [scheduleAutosave],
  )

  const handleBlockResizeEnd = useCallback(
    (blockId: string, width: number, height: number) => {
      savedBlockSizesRef.current[blockId] = { width, height }
      pendingRef.current.blocks.add(blockId)
      setDirty(true)
      scheduleAutosave()
    },
    [scheduleAutosave],
  )

  // При выходе из режима редактирования не оставляем таймеры висеть.
  useEffect(() => {
    if (editMode) return
    if (saveTimerRef.current != null) window.clearTimeout(saveTimerRef.current)
    if (retryTimerRef.current != null) window.clearTimeout(retryTimerRef.current)
    saveTimerRef.current = null
    retryTimerRef.current = null
    setSavePhase('idle')
  }, [editMode])

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

  const createChainLine = useCallback(
    async (fromId: string, fromName: string, toId: string, toName: string) => {
      const polesRaw = window.prompt('Сколько опор между ячейками?', '5')
      if (polesRaw === null) return
      const poles = Math.max(0, Math.min(200, Number(polesRaw) || 0))
      const mark = window.prompt('Марка провода/кабеля (например, АС-35)', 'АС-35')
      if (mark === null) return
      const kindRaw = window.prompt('Тип линии: overhead (ВЛ) или cable (кабель)', 'overhead')
      if (kindRaw === null) return
      const linkType = kindRaw.trim().toLowerCase() === 'cable' ? 'cable' : 'overhead'
      setSaving(true)
      setError(null)
      try {
        const created = await gisApi.createLineChain({
          from_asset_id: fromId,
          to_asset_id: toId,
          poles,
          cable_mark: mark.trim() || undefined,
          link_type: linkType,
        })
        const linkIds = created.link_ids
        const poleIds = created.poles.map((pole) => pole.id)
        pushCommand(
          `линия ${created.line_code} (${poles} опор)`,
          async () => {
            for (const id of linkIds) await gisApi.deleteLink(id)
            for (const id of poleIds) await gisApi.remove(id)
          },
          async () => {
            for (const id of poleIds) await gisApi.restoreAsset(id)
            for (const id of linkIds) await gisApi.restoreLink(id)
          },
        )
        setChainMode(false)
        setCellLinkMode(false)
        onGraphChanged()
        focusAsset(toId)
        setStatus(`Линия ${created.line_code} создана: ${fromName} → ${toName}, опор ${poles}`)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось создать линию')
      } finally {
        setSaving(false)
      }
    },
    [onGraphChanged, pushCommand, focusAsset],
  )

  const handleCellLink = useCallback(async (blockId: string, cellId: string, name: string) => {
    if (!cellLinkMode) return
    if (chainMode) {
      if (!cellLinkFirst) {
        setCellLinkFirst({ blockId, cellId, name })
        setStatus(`Линия: выбрана «${name}», кликните вторую ячейку`)
        return
      }
      if (cellLinkFirst.cellId === cellId) {
        setError('Выберите другую ячейку')
        return
      }
      const from = cellLinkFirst
      setCellLinkFirst(null)
      await createChainLine(from.cellId, from.name, cellId, name)
      return
    }
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
  }, [cellLinkMode, chainMode, cellLinkFirst, createChainLine, onGraphChanged, pushCommand])

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

  // --- этап 2: питание ячеек и переключение ---------------------------------

  /** Переключение ячейки или вводного разъединителя через toggle-API. */
  const handleToggleAsset = useCallback(
    async (assetId: string, next: 'on' | 'off') => {
      if (toggleBusyRef.current.has(assetId)) return
      toggleBusyRef.current.add(assetId)
      setError(null)
      try {
        const result = await gisApi.toggleAsset(assetId, { state: next })
        setCellStates((prev) => ({
          ...prev,
          [assetId]: { status: result.status, grounded: result.grounded, voltage_kv: result.voltage_kv },
        }))
        setStatus(
          result.energized
            ? `${result.name}: включено — под напряжением, ${voltageText(true, result.voltage_kv)}`
            : `${result.name}: отключено — обесточено`,
        )
        onGraphChanged()
      } catch (err) {
        if (err instanceof ApiError) {
          setError(
            err.status === 403
              ? 'Нет права переключать: нужен доступ «изменение состояния объекта»'
              : err.message,
          )
        } else {
          setError('Не удалось переключить объект')
        }
      } finally {
        toggleBusyRef.current.delete(assetId)
      }
    },
    [onGraphChanged],
  )

  /** Создано составное устройство по шаблону (`POST /api/schema/composite`). */
  const handleTemplateCreated = useCallback(
    (result: CompositeCreateResult) => {
      const parts = [`${result.children} элементов`]
      if (result.sections.length > 0) {
        parts.push(`секций: ${result.sections.length}`)
      }
      if (result.disconnector) parts.push('вводной разъединитель')
      setStatus(`Создано по шаблону: «${result.name}» — ${parts.join(', ')}`)
      onGraphChanged()
      focusAsset(result.id)
    },
    [focusAsset, onGraphChanged],
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
    onToggleCell: handleToggleAsset,
    onToggleNode: handleToggleAsset,
    onPortMove,
    onCellsMeasured: handleCellsMeasured,
    onCellDragEnd: handleCellDragEnd,
    onBlockResizeEnd: handleBlockResizeEnd,
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
      onToggleCell: handleToggleAsset,
      onToggleNode: handleToggleAsset,
      onPortMove,
      onCellsMeasured: handleCellsMeasured,
      onCellDragEnd: handleCellDragEnd,
      onBlockResizeEnd: handleBlockResizeEnd,
    }
  })

  // Полная сборка схемы только при смене графа: позиции из БД приоритетнее dagre
  useEffect(() => {
    const positions = nodePositions(graph)
    const flags = modeRef.current.flags
    const blockByAsset = new Map(graph.blocks.map((block) => [block.asset_id, block]))
    setNodes(
      graph.nodes.map((node) => {
        const blockData = blockByAsset.get(node.id)
        // Этап 3: размер блока из schema_width/schema_height (его же держит NodeResizer).
        // Пока размер не сохранён, узел авторазмерный — вёрстка не меняется.
        const blockSize = blockData ? blockSizeOf(blockData) : null
        return {
          id: node.id,
          type: 'asset',
          position: positions[node.id],
          width: blockSize?.width,
          height: blockSize?.height,
          selected: node.id === modeRef.current.selectedId,
          draggable: flags.draggable,
          data: {
            node,
            editable: flags.editable,
            portDrag: flags.portDrag,
            portPositions: portsForNode(node),
            onPortMove: (portId: string, x: number, y: number) =>
              handlersRef.current.onPortMove(node.id, portId, x, y),
            block: blockData,
            onSelectChild: (id: string) => handlersRef.current.onSelect(id),
            onAddCell: (id: string) => handlersRef.current.onAddCell(id),
            onAddCellsBulk: (id: string) => handlersRef.current.onAddCellsBulk(id),
            onDeleteCell: (assetId: string, cellId: string, name: string) =>
              handlersRef.current.onDeleteCell(assetId, cellId, name),
            onMoveCell: (assetId: string, cellId: string, name: string) =>
              handlersRef.current.onMoveCell(assetId, cellId, name),
            onToggleCollapse: (assetId: string, collapsed: boolean) =>
              handlersRef.current.onToggleCollapse(assetId, collapsed),
            onCellsMeasured: handlersRef.current.onCellsMeasured,
            onCellDragEnd: handlersRef.current.onCellDragEnd,
            onBlockResizeEnd: handlersRef.current.onBlockResizeEnd,
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
            canSwitch,
            cellStates: mergedCellStates,
            onToggleCell: (cellId: string, next: 'on' | 'off') =>
              void handlersRef.current.onToggleCell(cellId, next),
            onToggleNode: (assetId: string, next: 'on' | 'off') =>
              void handlersRef.current.onToggleNode(assetId, next),
          },
        }
      }),
    )
    setEdges(buildEdges(graph, positions))
    setDirty(false)
    setStatus(null)
    setError(null)
    setEdgeDraft(null)
    setPending(null)
    // Пересборка зависит только от графа: флаги режимов, статусы ячеек и выделение
    // применяются точечно отдельными эффектами, иначе каждая смена статуса
    // пересчитывала бы dagre и сбрасывала раскладку.
  }, [graph, setNodes, setEdges, canSwitch])

  // Статусы ячеек (реестр + локальные переключения) обновляем точечно, без дагре.
  useEffect(() => {
    setNodes((current) => {
      let changed = false
      const next = current.map((node) => {
        if (node.data.cellStates === mergedCellStates) return node
        changed = true
        return { ...node, data: { ...node.data, cellStates: mergedCellStates } }
      })
      return changed ? next : current
    })
  }, [mergedCellStates, setNodes])

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

  // Камеру подводим один раз при открытии схемы. Дальше граф перезагружается
  // после каждого переключения ячейки — сбрасывать зум в «показать всё» при этом
  // нельзя: оператор теряет место, где нажимал кнопку.
  const didFitRef = useRef(false)
  useEffect(() => {
    if (didFitRef.current) return
    didFitRef.current = true
    const timer = setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 60)
    return () => clearTimeout(timer)
  }, [graph, fitView])

  const saveCurrent = async () => {
    // Ручной триггер: отправляется всё накопленное, включая позиции всех узлов и порты.
    pendingRef.current.all = true
    setSaving(true)
    setError(null)
    try {
      await flushSaveRef.current(true)
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
    pendingRef.current.all = true
    scheduleAutosave()
    setStatus('Шаблон ГОСТ применён — сохраню автоматически')
  }

  const applyAuto = () => {
    const auto = dagrePositions(graph)
    setNodes((current) =>
      current.map((node) => ({ ...node, position: auto[node.id] ?? node.position })),
    )
    setDirty(true)
    pendingRef.current.all = true
    scheduleAutosave()
    setStatus('Авто-раскладка применена — сохраню автоматически')
  }

  type ConnectEndpoint =
    | { kind: 'asset'; assetId: string; port: AssetPort | null }
    | { kind: 'cell'; cellId: string; side: 'in' | 'out'; blockId: string }

  const cellOwnerMap = useMemo(() => cellBlockMap(graph), [graph])

  /** Куда ведёт конец линии: порт узла или порт ячейки внутри блока. */
  const resolveEndpoint = (
    assetId: string,
    handleId: string | null | undefined,
    role: 'source' | 'target',
  ): ConnectEndpoint | { error: string } => {
    const cell = parseCellHandle(handleId)
    if (cell) {
      const owner = cellOwnerMap[cell.cellId]
      if (!owner) return { error: 'Ячейка не найдена в блоке' }
      if (role === 'source' && cell.side !== 'out') {
        return { error: 'Линия от ячейки идёт только от выхода' }
      }
      if (role === 'target' && cell.side !== 'in') {
        return { error: 'Линия к ячейке идёт только на вход' }
      }
      return { kind: 'cell', cellId: cell.cellId, side: cell.side, blockId: owner.blockId }
    }
    const node = graph.nodes.find((item) => item.id === assetId)
    if (!node) return { error: 'Не найден объект связи' }
    const port =
      node.ports.find((item) => item.id === handleId) ??
      (role === 'source'
        ? node.ports.find((item) => item.kind === 'out' || item.kind === 'io')
        : node.ports.find((item) => item.kind === 'in' || item.kind === 'io'))
    if (port && role === 'source' && port.kind === 'in') {
      return { error: 'Соединять можно только выход со входом (OUT → IN)' }
    }
    if (port && role === 'target' && port.kind === 'out') {
      return { error: 'Соединять можно только выход со входом (OUT → IN)' }
    }
    // Порта может не быть (например, у опоры) — тогда связь через ячейку сама
    // создаст вход/выход через ports/ensure.
    return { kind: 'asset', assetId: node.id, port: port ?? null }
  }

  const resolveConnection = (
    connection: Connection,
  ): { source: ConnectEndpoint; target: ConnectEndpoint } | { error: string } => {
    const source = resolveEndpoint(connection.source, connection.sourceHandle, 'source')
    if ('error' in source) return source
    const target = resolveEndpoint(connection.target, connection.targetHandle, 'target')
    if ('error' in target) return target
    if (source.kind === 'asset' && target.kind === 'asset') {
      const fromKv = source.port?.nominal_voltage_kv
      const toKv = target.port?.nominal_voltage_kv
      if (fromKv != null && toKv != null && fromKv !== toKv) {
        return { error: `Напряжения не совпадают: ${fromKv} кВ и ${toKv} кВ` }
      }
    }
    return { source, target }
  }

  /**
   * Связь через порт ячейки: у ячейки может не быть портов (их создаёт
   * `POST /api/assets/{id}/ports/ensure`), затем обычный `POST /api/links`
   * получает from_port_id/to_port_id именно вложенного объекта.
   */
  const connectCellEndpoint = useCallback(
    async (source: ConnectEndpoint, target: ConnectEndpoint) => {
      setSaving(true)
      setError(null)
      try {
        const ensureIds = new Set<string>()
        if (source.kind === 'cell') ensureIds.add(source.cellId)
        if (target.kind === 'cell') ensureIds.add(target.cellId)
        if (source.kind === 'asset' && !source.port) ensureIds.add(source.assetId)
        if (target.kind === 'asset' && !target.port) ensureIds.add(target.assetId)
        for (const id of ensureIds) await gisApi.ensurePorts(id)
        const fromId = source.kind === 'asset' ? source.assetId : source.cellId
        const toId = target.kind === 'asset' ? target.assetId : target.cellId
        const [fromAsset, toAsset] = await Promise.all([gisApi.asset(fromId), gisApi.asset(toId)])
        const fromPort =
          source.kind === 'asset' && source.port
            ? source.port
            : fromAsset.ports.find((port) => port.kind !== 'in') ?? fromAsset.ports[0]
        const toPort =
          target.kind === 'asset' && target.port
            ? target.port
            : toAsset.ports.find((port) => port.kind !== 'out') ?? toAsset.ports[0]
        if (!fromPort || !toPort) {
          setError('Не удалось подобрать порты для связи — проверьте порты объектов')
          return
        }
        const created = await gisApi.createLink({
          from_port_id: fromPort.id,
          to_port_id: toPort.id,
          link_type: 'cable',
          cable_mark: `${fromAsset.name} → ${toAsset.name}`,
        })
        let linkId = created.id
        pushCommand(
          'связь через порт ячейки',
          async () => {
            await gisApi.deleteLink(linkId)
          },
          async () => {
            const again = await gisApi.restoreLink(linkId)
            linkId = again.id
          },
        )
        const cellPart = source.kind === 'cell' || target.kind === 'cell' ? ' (порт ячейки)' : ''
        setStatus(`Связь создана${cellPart}: ${fromAsset.name} → ${toAsset.name}`)
        onGraphChanged()
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Не удалось создать связь')
      } finally {
        setSaving(false)
      }
    },
    [onGraphChanged, pushCommand],
  )

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

  const autosaveInfo = saveIndicator(savePhase)
  const autosaveTone =
    autosaveInfo?.tone === 'bad'
      ? 'border-bad/60 bg-bad/10 text-bad'
      : autosaveInfo?.tone === 'ok'
        ? 'border-ok/50 bg-ok/10 text-ok'
        : autosaveInfo?.tone === 'accent'
          ? 'border-accent/50 bg-surface1/95 text-ink'
          : 'border-line bg-surface1/95 text-ink3'

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
            className="btn-ghost h-8 px-3"
            data-testid="schema-composite-open"
            title="Создать по шаблону: БКРУ (6 ячеек), ПС 35/6 (17 на секцию), КТП (вводной разъединитель)"
            onClick={() => setTemplateOpen(true)}
          >
            ▤ По шаблону
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
              <button
                type="button"
                className="btn-primary h-8 px-3"
                disabled={saving || savePhase === 'saving'}
                title="Ручной триггер: раскладка и так сохраняется автоматически через 2 с после изменения"
                onClick={() => void saveCurrent()}
              >
                {saving || savePhase === 'saving' ? 'Сохраняем…' : 'Сохранить раскладку'}
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
              <button
                type="button"
                className={`btn-ghost h-8 px-3 ${chainMode ? 'ring-1 ring-accent' : ''}`}
                title="Линия между ячейками через опоры: ВЛ или кабель, с маркой провода"
                onClick={() => {
                  setJumperMode(false)
                  setCableMode(false)
                  setCableFrom(null)
                  setCellLinkFirst(null)
                  setChainMode((value) => !value)
                  setCellLinkMode(!chainMode)
                  setStatus(chainMode ? null : 'Линия: кликните первую ячейку, затем вторую — укажите число опор, марку и тип')
                }}
              >
                Линия
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
                {portDrag
                  ? 'тяните кружки по краю узла'
                  : 'угол блока — размер · ⠿ на ячейке — перетащить внутри блока'}
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

      {/* Этап 3: индикатор автосейва — «Сохранение…» / зелёный успех / красная ошибка с повтором. */}
      {editMode && canEdit && autosaveInfo ? (
        <div
          role={savePhase === 'error' ? 'alert' : 'status'}
          aria-live={savePhase === 'error' ? 'assertive' : 'polite'}
          data-testid="schema-autosave"
          data-phase={savePhase}
          className={`absolute left-1/2 top-2 z-[13] flex -translate-x-1/2 items-center gap-2 rounded-lg border px-3 py-1.5 text-[12px] shadow-lg backdrop-blur ${autosaveTone}`}
        >
          {autosaveInfo.spinner ? <span className="schema-spinner" aria-hidden="true" /> : null}
          <span>{autosaveInfo.text}</span>
          {savePhase === 'error' ? (
            <button
              type="button"
              className="rounded border border-bad/50 px-1.5 text-[11px] hover:bg-bad/10"
              title="Повторить сохранение сейчас"
              onClick={() => void flushSaveRef.current(true)}
            >
              Повторить
            </button>
          ) : null}
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
        onNodeDragStop={(_, dragged) => {
          const before = dragStartPositions.current
          const after = snapshotPositions()
          if (before) {
            pushHistory({ kind: 'positions', before, after })
          }
          dragStartPositions.current = null
          setGuides(null)
          setDirty(true)
          // Этап 3: отпустили узел — через 2 с позиция уйдёт автосейвом.
          pendingRef.current.nodes.add(dragged.id)
          scheduleAutosave()
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
          // Линия от порта ячейки: подсветку совместимых портов узла не включаем.
          if (parseCellHandle(params.handleId)) {
            setActiveConnection(null)
            return
          }
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
          if (
            connection.source === connection.target &&
            !parseCellHandle(connection.sourceHandle) &&
            !parseCellHandle(connection.targetHandle)
          ) {
            return false
          }
          const resolved = resolveConnection(connection)
          if ('error' in resolved) return false
          if (
            resolved.source.kind === 'asset' &&
            resolved.target.kind === 'asset' &&
            (!resolved.source.port || !resolved.target.port)
          ) {
            return false
          }
          return true
        }}
        onConnect={(connection) => {
          if (!editMode || portDrag) return
          const resolved = resolveConnection(connection)
          if ('error' in resolved) {
            setError(resolved.error)
            setPending(null)
            return
          }
          // Этап 3: связь через порт ячейки создаётся сразу — порт вложенного
          // объекта уже известен (ensure + POST /api/links с портами ячейки).
          if (resolved.source.kind === 'cell' || resolved.target.kind === 'cell') {
            setPending(null)
            void connectCellEndpoint(resolved.source, resolved.target)
            return
          }
          if (connection.source === connection.target) return
          if (resolved.source.kind !== 'asset' || resolved.target.kind !== 'asset') return
          if (!resolved.source.port || !resolved.target.port) {
            setError('У объекта нет порта — создайте вход/выход в карточке или режиме портов')
            setPending(null)
            return
          }
          setPending({
            ...connection,
            sourceHandle: resolved.source.port.id,
            targetHandle: resolved.target.port.id,
          })
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

      <CompositeTemplateDialog
        open={templateOpen}
        center={templateOpen ? addCenter() : { x: 240, y: 200 }}
        onClose={() => setTemplateOpen(false)}
        onCreated={handleTemplateCreated}
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
            <div className="text-[10px] uppercase tracking-wide text-ink3">Ячейки и разъединители</div>
            <div className="text-ink2">
              <span style={{ color: POWER_COLOR.on }}>⚡</span> ячейка включена — под напряжением (красный)
            </div>
            <div className="text-ink2">
              <span style={{ color: POWER_COLOR.off }}>○</span> ячейка отключена / заземлена — обесточено (зелёный)
            </div>
            <div className="text-ink3">№ — номер ячейки, подпись — вводная/отходящая/секционная</div>
            <div className="text-ink3">кнопка «Вкл/Откл» — переключение через API, запись в аудит</div>
          </div>
          <div className="mb-2 space-y-0.5 border-b border-line pb-2">
            <div className="text-[10px] uppercase tracking-wide text-ink3">Блок и ячейки (этап 3)</div>
            <div className="text-ink2">угол блока — маркеры ресайза, размер сохраняется в БД</div>
            <div className="text-ink2">⠿ на ячейке — перетаскивание внутри блока (за рамки не выйдет)</div>
            <div className="text-ink2">кружки на ячейках — порты: линия встаёт на порт ячейки</div>
            <div className="text-ink3">изменения уходят автосейвом через 2 с после отпускания</div>
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
  canSwitch = false,
  assetStates = {},
  onGraphChanged,
}: {
  graph: TopologyGraph
  selectedId: string | null
  onSelect: (id: string) => void
  canEdit?: boolean
  /** Право `asset.status.edit`: кнопки «Включить/Отключить» у ячеек и разъединителей. */
  canSwitch?: boolean
  /** Статусы объектов реестра: от них зависит цвет ячеек внутри блоков. */
  assetStates?: Record<string, CellPowerState>
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
          canSwitch={canSwitch}
          assetStates={assetStates}
          onGraphChanged={onGraphChanged ?? (() => undefined)}
        />
      </div>
    </ReactFlowProvider>
  )
}
