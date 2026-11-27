/**
 * Этап 3 «Продвинутая интерактивность схемы»: чистые помощники раскладки блока.
 *
 * Здесь нет React и DOM — только арифметика, которую проверяют тесты
 * (`schemaStage3.test.ts`): размеры блока, координаты ячеек внутри блока,
 * идентификаторы портов ячеек, автосейв (debounce/retry) и разбиение
 * PUT /api/topology/layout на пачки (у эндпоинта лимит 500 items).
 */

import type { GraphBlock, SchemaLayoutItem } from './gis'

/** Ширина блока по умолчанию — как в вёрстке узла (`w-[320px]`). */
export const BLOCK_DEFAULT_WIDTH = 320
/** Минимумы ресайза. Backend принимает 120×80, в UI оставляем запас на шапку. */
export const BLOCK_MIN_WIDTH = 160
export const BLOCK_MIN_HEIGHT = 120
/** Ячейки внутри блока: ширина колонки и зазор — те же, что у CSS-grid. */
export const CELL_MIN_WIDTH = 132
export const CELL_GAP = 4
/** Внутренние отступы контента блока (`px-2.5`). */
export const BLOCK_PADDING = 10

/** Задержка автосейва после отпускания узла/маркера ресайза. */
export const AUTOSAVE_DEBOUNCE_MS = 2000
/** Повтор после ошибки сохранения (нет сети / 500). */
export const AUTOSAVE_RETRY_MS = 5000
/** Лимит элементов в одном PUT /api/topology/layout (backend: max_length=500). */
export const LAYOUT_CHUNK_SIZE = 200

export interface Size {
  width: number
  height: number
}

export interface BlockSize {
  width?: number
  height?: number
}

/** Прямоугольник ячейки в координатах контента блока. */
export interface CellBox {
  x: number
  y: number
  width: number
  height: number
}

export interface CellLocal {
  x: number
  y: number
}

/** Ширина колонки ячейки при данной ширине блока (повторяет auto-fill/minmax). */
export function cellWidthForBlock(blockWidth: number): number {
  const usable = Math.max(CELL_MIN_WIDTH, blockWidth - BLOCK_PADDING * 2)
  const columns = Math.max(1, Math.floor((usable + CELL_GAP) / (CELL_MIN_WIDTH + CELL_GAP)))
  return Math.floor((usable - (columns - 1) * CELL_GAP) / columns)
}

/** Вписать ячейку в контент блока: рамки родителя — жёсткое ограничение (extent). */
export function clampCellBox(box: CellBox, bounds: Size): CellLocal {
  const maxX = Math.max(0, bounds.width - box.width)
  const maxY = Math.max(0, bounds.height - box.height)
  return {
    x: Math.min(Math.max(0, box.x), maxX),
    y: Math.min(Math.max(0, box.y), maxY),
  }
}

export function roundLayoutValue(value: number): number {
  return Math.round(value)
}

/**
 * Размер блока из графа: приоритет у колонок этапа 3 (`schema_width`/`schema_height`),
 * затем исторические `width`/`height` (их же отдаёт backend для контуров).
 * Свёрнутый блок размер не несёт — он рисуется компактной карточкой.
 */
export function blockSizeOf(
  block: Pick<GraphBlock, 'schema_width' | 'schema_height' | 'width' | 'height' | 'collapsed'>,
): BlockSize | null {
  if (block.collapsed) return null
  const width = block.schema_width ?? block.width ?? null
  const height = block.schema_height ?? block.height ?? null
  if (width == null && height == null) return null
  const size: BlockSize = {}
  if (width != null && width > 0) size.width = Number(width)
  if (height != null && height > 0) size.height = Number(height)
  return size.width == null && size.height == null ? null : size
}

/**
 * Координаты ячеек, сохранённые в `schema_local_x/y` (этап 3).
 *
 * Возвращаем `null`, если блок ещё не проходил через этап 3 (нет `schema_width`)
 * или хотя бы одна ячейка без координат/вне рамок: тогда блок рисуется обычной
 * сеткой, а не «рассыпанными» координатами старых импортов.
 */
export function explicitCellLayout(
  block: Pick<GraphBlock, 'schema_width' | 'schema_height' | 'children'>,
): Record<string, CellLocal> | null {
  const width = block.schema_width
  if (width == null || width <= 0) return null
  const height = block.schema_height
  const result: Record<string, CellLocal> = {}
  for (const child of block.children) {
    if (child.role === 'busbar') continue
    if (child.local_x == null || child.local_y == null) return null
    if (child.local_x < 0 || child.local_y < 0) return null
    if (child.local_x > width) return null
    if (height != null && height > 0 && child.local_y > height) return null
    result[child.id] = { x: Number(child.local_x), y: Number(child.local_y) }
  }
  return Object.keys(result).length > 0 ? result : null
}

/** Идентификатор порта-ячейки внутри узла блока: `cell:<id>:in|out`. */
export function cellHandleId(cellId: string, side: 'in' | 'out'): string {
  return `cell:${cellId}:${side}`
}

export function parseCellHandle(handleId: string | null | undefined): { cellId: string; side: 'in' | 'out' } | null {
  if (!handleId) return null
  const match = /^cell:([^:]+):(in|out)$/.exec(handleId)
  if (!match) return null
  return { cellId: match[1], side: match[2] as 'in' | 'out' }
}

/** PUT /api/topology/layout ограничен 500 элементами — режем на пачки. */
export function chunkItems<T>(items: T[], size: number = LAYOUT_CHUNK_SIZE): T[][] {
  if (size <= 0) return items.length > 0 ? [items] : []
  const chunks: T[][] = []
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size))
  }
  return chunks
}

/** Состояние индикатора автосейва. */
export type SavePhase = 'idle' | 'pending' | 'saving' | 'saved' | 'error'
export type SaveEvent = 'schedule' | 'start' | 'success' | 'fail' | 'reset'

export function nextSavePhase(phase: SavePhase, event: SaveEvent): SavePhase {
  if (event === 'reset') return 'idle'
  if (event === 'schedule') return phase === 'saving' ? phase : 'pending'
  if (event === 'start') return 'saving'
  if (event === 'success') return 'saved'
  return 'error'
}

export interface SaveIndicatorInfo {
  text: string
  tone: 'muted' | 'accent' | 'ok' | 'bad'
  spinner: boolean
}

export function saveIndicator(phase: SavePhase): SaveIndicatorInfo | null {
  switch (phase) {
    case 'pending':
      return { text: 'Изменения не сохранены — сохраню автоматически', tone: 'muted', spinner: false }
    case 'saving':
      return { text: 'Сохранение…', tone: 'accent', spinner: true }
    case 'saved':
      return { text: 'Все изменения сохранены ✓', tone: 'ok', spinner: false }
    case 'error':
      return { text: 'Ошибка сохранения, проверьте сеть', tone: 'bad', spinner: false }
    default:
      return null
  }
}

export interface BlockLayoutInput {
  /** id блока (gis.assets) */
  assetId: string
  /** абсолютная позиция блока на холсте */
  position: CellLocal
  /** размер блока: сохраняется, только если он валиден (минимумы backend) */
  size: Size | null
  /** ячейки блока с локальными координатами (уже вписанные в рамки) */
  cells: Array<{ id: string; local: CellLocal }>
}

/**
 * Элементы раскладки для блока: сам блок (x/y + width/height) и его ячейки
 * (local_x/local_y). Один запрос — и размер, и позиции ячеек.
 */
export function blockLayoutItems(input: BlockLayoutInput): SchemaLayoutItem[] {
  const item: SchemaLayoutItem = {
    asset_id: input.assetId,
    x: roundLayoutValue(input.position.x),
    y: roundLayoutValue(input.position.y),
  }
  if (
    input.size != null &&
    input.size.width >= BLOCK_MIN_WIDTH &&
    input.size.height >= BLOCK_MIN_HEIGHT
  ) {
    item.width = roundLayoutValue(input.size.width)
    item.height = roundLayoutValue(input.size.height)
  }
  const items: SchemaLayoutItem[] = [item]
  for (const cell of input.cells) {
    items.push({
      asset_id: cell.id,
      local_x: roundLayoutValue(cell.local.x),
      local_y: roundLayoutValue(cell.local.y),
    })
  }
  return items
}
