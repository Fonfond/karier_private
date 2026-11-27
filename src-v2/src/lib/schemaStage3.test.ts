/**
 * Этап 3: проверки арифметики раскладки блока и автосейва.
 * DOM/React не нужны — тестируются чистые функции из `schemaStage3.ts`.
 */

import { describe, expect, it } from 'vitest'
import {
  AUTOSAVE_DEBOUNCE_MS,
  AUTOSAVE_RETRY_MS,
  BLOCK_MIN_HEIGHT,
  BLOCK_MIN_WIDTH,
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
} from './schemaStage3'
import type { GraphBlock } from './gis'

function block(partial: Partial<GraphBlock> & { children?: GraphBlock['children'] }): GraphBlock {
  return {
    asset_id: 'block-1',
    code: 'PS-1',
    name: 'ПС 35/6',
    block_code: 'ps_35_6',
    schema_x: 0,
    schema_y: 0,
    children: [],
    ...partial,
  } as GraphBlock
}

function child(id: string, local: { x: number | null; y: number | null }, role: string | null = 'outgoing') {
  return {
    id,
    code: id,
    name: `Яч. ${id}`,
    role,
    local_x: local.x,
    local_y: local.y,
    type_name: 'Ячейка',
    params: {},
  }
}

describe('cellWidthForBlock', () => {
  it('320 px → две колонки по 148 px (шапка и отступы не съезжают)', () => {
    expect(cellWidthForBlock(320)).toBe(148)
  })

  it('узкий блок 160 px → одна колонка на всю доступную ширину', () => {
    expect(cellWidthForBlock(160)).toBe(140)
  })

  it('широкий блок даёт больше колонок, но не меньше минимальной ширины', () => {
    const width = cellWidthForBlock(640)
    expect(width).toBeGreaterThanOrEqual(CELL_MIN_WIDTH)
    expect(width).toBe(152)
    // 4 колонки по 152 + 3 зазора + 2 отступа ровно укладываются в 640
    expect(width * 4 + 3 * 4 + 2 * 10).toBe(640)
  })

  it('не опускается ниже минимальной ширины даже для вырожденного размера', () => {
    expect(cellWidthForBlock(40)).toBe(CELL_MIN_WIDTH)
  })
})

describe('clampCellBox — ограничение рамками блока (extent parent)', () => {
  const bounds = { width: 300, height: 200 }
  const box = { x: 0, y: 0, width: 148, height: 44 }

  it('оставляет координаты внутри рамок как есть', () => {
    expect(clampCellBox({ ...box, x: 20, y: 30 }, bounds)).toEqual({ x: 20, y: 30 })
  })

  it('не выпускает ячейку за правый/нижний край', () => {
    expect(clampCellBox({ ...box, x: 500, y: 500 }, bounds)).toEqual({ x: 152, y: 156 })
  })

  it('не выпускает ячейку за левый/верхний край', () => {
    expect(clampCellBox({ ...box, x: -100, y: -5 }, bounds)).toEqual({ x: 0, y: 0 })
  })

  it('ячейка шире блока прижимается к 0, а не уходит в минус', () => {
    expect(clampCellBox({ ...box, width: 400, x: 30, y: 10 }, bounds)).toEqual({ x: 0, y: 10 })
  })
})

describe('blockSizeOf', () => {
  it('приоритет у schema_width/schema_height (этап 3)', () => {
    expect(blockSizeOf(block({ schema_width: 480, schema_height: 360, width: 320, height: 220 }))).toEqual({
      width: 480,
      height: 360,
    })
  })

  it('старые контуры берут width/height, если новых колонок нет', () => {
    expect(blockSizeOf(block({ width: 420, height: 260 }))).toEqual({ width: 420, height: 260 })
  })

  it('без размеров возвращает null — узел остаётся авторазмерным', () => {
    expect(blockSizeOf(block({}))).toBeNull()
  })

  it('свёрнутый блок не растягивается', () => {
    expect(blockSizeOf(block({ collapsed: true, schema_width: 480, schema_height: 360 }))).toBeNull()
  })
})

describe('explicitCellLayout', () => {
  it('все ячейки с координатами внутри рамок → раскладка из БД', () => {
    const layout = explicitCellLayout(
      block({
        schema_width: 320,
        schema_height: 240,
        children: [child('c1', { x: 10, y: 10 }), child('c2', { x: 160, y: 10 }), child('bus', { x: null, y: null }, 'busbar')],
      }),
    )
    expect(layout).toEqual({ c1: { x: 10, y: 10 }, c2: { x: 160, y: 10 } })
  })

  it('блок без schema_width (не проходил этап 3) → null, рисуется сеткой', () => {
    expect(
      explicitCellLayout(block({ children: [child('c1', { x: 10, y: 10 })] })),
    ).toBeNull()
  })

  it('ячейка без координат → null: смешивать сетку и абсолютные позиции нельзя', () => {
    expect(
      explicitCellLayout(
        block({
          schema_width: 320,
          schema_height: 240,
          children: [child('c1', { x: 10, y: 10 }), child('c2', { x: null, y: null })],
        }),
      ),
    ).toBeNull()
  })

  it('координаты за рамками блока (старый импорт) → null', () => {
    expect(
      explicitCellLayout(
        block({
          schema_width: 320,
          schema_height: 240,
          children: [child('c1', { x: 660, y: 140 })],
        }),
      ),
    ).toBeNull()
    expect(
      explicitCellLayout(
        block({
          schema_width: 320,
          schema_height: 240,
          children: [child('c1', { x: 10, y: 900 })],
        }),
      ),
    ).toBeNull()
  })

  it('пустой блок → null', () => {
    expect(explicitCellLayout(block({ schema_width: 320, schema_height: 240 }))).toBeNull()
  })
})

describe('cellHandleId / parseCellHandle', () => {
  it('порт ячейки кодируется в handle id и разбирается обратно', () => {
    const id = cellHandleId('c1', 'out')
    expect(id).toBe('cell:c1:out')
    expect(parseCellHandle(id)).toEqual({ cellId: 'c1', side: 'out' })
  })

  it('обычные порты узла не считаются портами ячейки', () => {
    expect(parseCellHandle('l-in')).toBeNull()
    expect(parseCellHandle('')).toBeNull()
    expect(parseCellHandle(null)).toBeNull()
  })

  it('битые handle id не ломают разбор', () => {
    expect(parseCellHandle('cell:c1')).toBeNull()
    expect(parseCellHandle('cell:c1:sideways')).toBeNull()
  })
})

describe('chunkItems — лимит PUT /api/topology/layout', () => {
  it('маленький список уходит одним запросом', () => {
    expect(chunkItems([1, 2, 3], 100)).toEqual([[1, 2, 3]])
  })

  it('большой список режется по 200 элементов (лимит backend 500)', () => {
    const items = Array.from({ length: LAYOUT_CHUNK_SIZE * 2 + 5 }, (_, index) => index)
    const chunks = chunkItems(items)
    expect(chunks).toHaveLength(3)
    expect(chunks[0]).toHaveLength(LAYOUT_CHUNK_SIZE)
    expect(chunks[2]).toHaveLength(5)
    expect(chunks.flat()).toEqual(items)
  })

  it('пустой список — ноль пачек', () => {
    expect(chunkItems([])).toEqual([])
  })
})

describe('автосейв: задержки и индикатор', () => {
  it('задержки соответствуют контракту: 2 с и повтор 5 с', () => {
    expect(AUTOSAVE_DEBOUNCE_MS).toBe(2000)
    expect(AUTOSAVE_RETRY_MS).toBe(5000)
  })

  it('переходы состояния автосейва', () => {
    expect(nextSavePhase('idle', 'schedule')).toBe('pending')
    expect(nextSavePhase('pending', 'start')).toBe('saving')
    expect(nextSavePhase('saving', 'success')).toBe('saved')
    expect(nextSavePhase('saving', 'fail')).toBe('error')
    expect(nextSavePhase('error', 'start')).toBe('saving')
    expect(nextSavePhase('error', 'success')).toBe('saved')
    expect(nextSavePhase('saved', 'reset')).toBe('idle')
  })

  it('во время запроса новые изменения не гасят индикатор «Сохранение…»', () => {
    expect(nextSavePhase('saving', 'schedule')).toBe('saving')
  })

  it('подписи индикатора', () => {
    expect(saveIndicator('idle')).toBeNull()
    expect(saveIndicator('saving')).toMatchObject({ text: 'Сохранение…', spinner: true, tone: 'accent' })
    expect(saveIndicator('saved')).toMatchObject({ text: 'Все изменения сохранены ✓', tone: 'ok', spinner: false })
    expect(saveIndicator('error')).toMatchObject({
      text: 'Ошибка сохранения, проверьте сеть',
      tone: 'bad',
      spinner: false,
    })
  })
})

describe('blockLayoutItems — тело PUT /api/topology/layout', () => {
  it('блок сохраняет позицию и размер, ячейки — local_x/local_y', () => {
    const items = blockLayoutItems({
      assetId: 'block-1',
      position: { x: 120.4, y: 80.6 },
      size: { width: 480, height: 360 },
      cells: [
        { id: 'c1', local: { x: 10.2, y: 20.7 } },
        { id: 'c2', local: { x: 170, y: 20 } },
      ],
    })
    expect(items).toEqual([
      { asset_id: 'block-1', x: 120, y: 81, width: 480, height: 360 },
      { asset_id: 'c1', local_x: 10, local_y: 21 },
      { asset_id: 'c2', local_x: 170, local_y: 20 },
    ])
  })

  it('слишком маленький размер не отправляется (backend вернул бы 422)', () => {
    const items = blockLayoutItems({
      assetId: 'block-1',
      position: { x: 0, y: 0 },
      size: { width: BLOCK_MIN_WIDTH - 1, height: BLOCK_MIN_HEIGHT - 1 },
      cells: [],
    })
    expect(items).toEqual([{ asset_id: 'block-1', x: 0, y: 0 }])
    expect(items[0].width).toBeUndefined()
  })

  it('без размера (авторазмерный блок) уходит только позиция', () => {
    const items = blockLayoutItems({
      assetId: 'block-1',
      position: { x: 40, y: 60 },
      size: null,
      cells: [],
    })
    expect(items).toEqual([{ asset_id: 'block-1', x: 40, y: 60 }])
  })
})
