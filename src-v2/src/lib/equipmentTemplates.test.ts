/**
 * Тесты разбора шаблонов составных устройств (этап 2 модели оборудования).
 *
 * Фикстуры — реальный формат `composite_template` v2 из миграции
 * `backend-v2/alembic/versions/0016_stage2_equipment.py` (БКРУ 6 ячеек,
 * ПС 35/6 — 2 секции по 17, КТП — 0 ячеек + вводной разъединитель).
 */

import { describe, expect, it } from 'vitest'
import type { AssetType } from './gis'
import {
  CELL_KIND_TITLES,
  MAX_CELLS_PER_SECTION,
  MIN_CELLS_PER_SECTION,
  PS_DEFAULT_CELLS,
  buildSectionPreview,
  builtinTemplate,
  cellKindOf,
  cellKindTitle,
  cellNumberFromName,
  cellsLabel,
  elementsLabel,
  parseCompositeTemplate,
  pluralRu,
  previewTotals,
  profileForType,
  psSectionCells,
  templateForType,
  templateSummary,
  templateTitle,
  validateCellsPerSection,
} from './equipmentTemplates'

const BKRU_TEMPLATE = [
  { version: 2, profile: 'bkru', title: 'БКРУ (6 ячеек)', configurable: false, cells: 6 },
  {
    version: 2,
    section_no: 1,
    label: 'Секция 1',
    voltage_kv: 6,
    cells: [
      { cell_kind: 'in', count: 1, label: 'Вводная', voltage_kv: 6 },
      { cell_kind: 'out', count: 2, label: 'Отходящая', voltage_kv: 6 },
      { cell_kind: 'sectional', count: 1, label: 'Секционная', voltage_kv: 6 },
    ],
  },
  {
    version: 2,
    section_no: 2,
    label: 'Секция 2',
    voltage_kv: 6,
    cells: [
      { cell_kind: 'out', count: 1, label: 'Отходящая', voltage_kv: 6 },
      { cell_kind: 'in', count: 1, label: 'Вводная', voltage_kv: 6 },
    ],
  },
]

const PS_TEMPLATE = [
  {
    version: 2,
    profile: 'ps_35_6',
    title: 'ПС 35/6 кВ (17 ячеек на секцию)',
    configurable: true,
    cells_per_section: 17,
    section_count: 2,
  },
  {
    version: 2,
    section_no: 1,
    label: 'Секция 1 (35 кВ)',
    voltage_kv: 35,
    cells: [
      { cell_kind: 'in', count: 1, label: 'Вводная', voltage_kv: 35 },
      { cell_kind: 'out', count: 15, label: 'Отходящая', voltage_kv: 35 },
      { cell_kind: 'sectional', count: 1, label: 'Секционная', voltage_kv: 35 },
    ],
  },
  {
    version: 2,
    section_no: 2,
    label: 'Секция 2 (6 кВ)',
    voltage_kv: 6,
    cells: [
      { cell_kind: 'in', count: 1, label: 'Вводная', voltage_kv: 6 },
      { cell_kind: 'out', count: 15, label: 'Отходящая', voltage_kv: 6 },
      { cell_kind: 'sectional', count: 1, label: 'Секционная', voltage_kv: 6 },
    ],
  },
]

const KTP_TEMPLATE = [
  {
    version: 2,
    profile: 'ktp',
    title: 'КТП (без ячеек, вводной разъединитель)',
    configurable: false,
    cells: 0,
    disconnector: {
      cell_kind: 'in',
      type_code: 'razedinitel',
      label: 'Вводной разъединитель',
      voltage_kv: 6,
    },
  },
]

function makeType(partial: Partial<AssetType> & { code: string; name: string }): AssetType {
  return {
    id: partial.code,
    category: 'equipment',
    schema_symbol: 'load',
    icon: null,
    color: null,
    port_template: {},
    attr_schema: {},
    required_attrs: [],
    is_mobile_default: false,
    sort_order: 100,
    is_active: true,
    description: null,
    parent_id: null,
    parent_name: null,
    assets_count: 0,
    ...partial,
  }
}

describe('parseCompositeTemplate: v2-массив', () => {
  it('БКРУ — ровно 6 ячеек в двух секциях', () => {
    const template = parseCompositeTemplate(BKRU_TEMPLATE)
    expect(template.isV2).toBe(true)
    expect(template.profile).toBe('bkru')
    expect(template.configurable).toBe(false)
    expect(template.sections).toHaveLength(2)
    expect(template.totalCells).toBe(6)
    expect(template.sections[0].cells.map((cell) => [cell.cell_kind, cell.count])).toEqual([
      ['in', 1],
      ['out', 2],
      ['sectional', 1],
    ])
    expect(template.sections[1].cells.map((cell) => [cell.cell_kind, cell.count])).toEqual([
      ['out', 1],
      ['in', 1],
    ])
  })

  it('ПС 35/6 — 2 секции × 17 ячеек, настраиваемый параметр 17', () => {
    const template = parseCompositeTemplate(PS_TEMPLATE)
    expect(template.profile).toBe('ps_35_6')
    expect(template.configurable).toBe(true)
    expect(template.cellsPerSection).toBe(17)
    expect(template.totalCells).toBe(34)
    const preview = buildSectionPreview(template, template.cellsPerSection)
    expect(preview).toHaveLength(2)
    expect(preview[0].total).toBe(17)
    expect(preview[1].total).toBe(17)
    expect(previewTotals(template, 17)).toEqual({
      cells: 34,
      sections: 2,
      hasDisconnector: false,
      children: 34,
    })
  })

  it('КТП — 0 ячеек и вводной разъединитель', () => {
    const template = parseCompositeTemplate(KTP_TEMPLATE)
    expect(template.profile).toBe('ktp')
    expect(template.sections).toHaveLength(0)
    expect(template.totalCells).toBe(0)
    expect(template.disconnector).toEqual({
      cell_kind: 'in',
      type_code: 'razedinitel',
      label: 'Вводной разъединитель',
      voltage_kv: 6,
    })
    expect(previewTotals(template)).toEqual({
      cells: 0,
      sections: 0,
      hasDisconnector: true,
      children: 1,
    })
    expect(templateSummary(template)).toBe('0 ячеек · вводной разъединитель')
  })

  it('legacy v1 не считается шаблоном этапа 2', () => {
    const template = parseCompositeTemplate([{ type_code: 'cell', count: 5, label: 'Ячейка' }])
    expect(template.isV2).toBe(false)
    expect(template.totalCells).toBe(0)
  })

  it('пустой/битый шаблон не падает', () => {
    expect(parseCompositeTemplate(null).isV2).toBe(false)
    expect(parseCompositeTemplate([]).isV2).toBe(false)
    expect(parseCompositeTemplate('строка').isV2).toBe(false)
    expect(parseCompositeTemplate([{ section_no: 1, cells: 'нет' }]).isV2).toBe(false)
  })

  it('dict плана 31 (sections/cells) тоже читается', () => {
    const template = parseCompositeTemplate({
      profile: 'ktp',
      configurable: false,
      disconnector: { cell_kind: 'in', type_code: 'razedinitel' },
    })
    expect(template.isV2).toBe(true)
    expect(template.disconnector?.type_code).toBe('razedinitel')
  })
})

describe('профили и встроенные шаблоны', () => {
  it('profileForType повторяет backend: КТП раньше ПС', () => {
    expect(profileForType('bkru', 'БКРУ-1')).toBe('bkru')
    expect(profileForType('ktp', 'КТП (комплектная трансформаторная подстанция)')).toBe('ktp')
    expect(profileForType('substation', 'ПС 35/6 кВ')).toBe('ps_35_6')
    expect(profileForType('ps_35_6_kv_2', 'Подстанция')).toBe('ps_35_6')
    expect(profileForType('op', 'Опора')).toBeNull()
  })

  it('встроенный БКРУ — 6 ячеек', () => {
    const template = builtinTemplate('bkru')
    expect(template.totalCells).toBe(6)
    expect(template.configurable).toBe(false)
    expect(templateSummary(template)).toBe('2 секции · 6 ячеек')
    expect(templateTitle(template)).toContain('БКРУ')
  })

  it('встроенный ПС — 34 ячейки и параметр по умолчанию 17', () => {
    const template = builtinTemplate('ps_35_6')
    expect(template.totalCells).toBe(34)
    expect(template.cellsPerSection).toBe(PS_DEFAULT_CELLS)
    expect(templateSummary(template)).toContain('34 ячеек')
    expect(templateTitle(template)).toContain('ПС 35/6')
  })

  it('встроенный КТП — только разъединитель', () => {
    const template = builtinTemplate('ktp')
    expect(template.sections).toHaveLength(0)
    expect(template.disconnector?.label).toBe('Вводной разъединитель')
    expect(templateTitle(template)).toContain('КТП')
  })

  it('templateForType берёт v2 из API, иначе встроенный профиль', () => {
    const typed = makeType({ code: 'bkru', name: 'БКРУ', composite_template: BKRU_TEMPLATE })
    expect(templateForType(typed).totalCells).toBe(6)

    const noTemplate = makeType({ code: 'substation', name: 'ПС 35/6 кВ', composite_template: [] })
    expect(templateForType(noTemplate).totalCells).toBe(34)

    const unknown = makeType({ code: 'op', name: 'Опора' })
    expect(templateForType(unknown).isV2).toBe(false)
  })
})

describe('ПС: пересборка секции под «Ячеек на секцию»', () => {
  it('состав секции: вводная + отходящие + секционная', () => {
    expect(psSectionCells(17)).toEqual([
      { cell_kind: 'in', count: 1 },
      { cell_kind: 'out', count: 15 },
      { cell_kind: 'sectional', count: 1 },
    ])
    expect(psSectionCells(3)).toEqual([
      { cell_kind: 'in', count: 1 },
      { cell_kind: 'out', count: 1 },
      { cell_kind: 'sectional', count: 1 },
    ])
    expect(psSectionCells(2)).toEqual([
      { cell_kind: 'in', count: 1 },
      { cell_kind: 'out', count: 0 },
      { cell_kind: 'sectional', count: 1 },
    ])
    expect(psSectionCells(1)).toEqual([{ cell_kind: 'in', count: 1 }])
  })

  it('ровно n ячеек на секцию при n ≥ 2 (как backend build_layout)', () => {
    const template = parseCompositeTemplate(PS_TEMPLATE)
    for (const n of [2, 3, 10, 17, 50]) {
      const preview = buildSectionPreview(template, n)
      expect(preview).toHaveLength(2)
      for (const section of preview) expect(section.total).toBe(n)
      expect(previewTotals(template, n).cells).toBe(n * 2)
    }
  })

  it('настройка не влияет на БКРУ/КТП', () => {
    const bkru = parseCompositeTemplate(BKRU_TEMPLATE)
    expect(previewTotals(bkru, 10).cells).toBe(6)
    const ktp = parseCompositeTemplate(KTP_TEMPLATE)
    expect(previewTotals(ktp, 10).children).toBe(1)
  })
})

describe('validateCellsPerSection: 1…50', () => {
  it('границы из Pydantic ge=1, le=50', () => {
    expect(validateCellsPerSection(1)).toBeNull()
    expect(validateCellsPerSection(17)).toBeNull()
    expect(validateCellsPerSection(50)).toBeNull()
    expect(validateCellsPerSection('17')).toBeNull()
    expect(validateCellsPerSection(0)).toContain('от 1 до 50')
    expect(validateCellsPerSection(51)).toContain('от 1 до 50')
    expect(validateCellsPerSection('')).toContain('Укажите')
    expect(validateCellsPerSection('abc')).toContain('числом')
    expect(validateCellsPerSection(2.5)).toContain('целым')
    expect(MIN_CELLS_PER_SECTION).toBe(1)
    expect(MAX_CELLS_PER_SECTION).toBe(50)
  })
})

describe('ячейки на схеме: вид и номер', () => {
  it('вид из params схемы или из старой роли', () => {
    expect(cellKindOf({ cell_kind: 'in' }, 'incoming')).toBe('in')
    expect(cellKindOf({ cell_kind: 'sectional' }, 'section')).toBe('sectional')
    expect(cellKindOf({}, 'incoming')).toBe('in')
    expect(cellKindOf({}, 'outgoing')).toBe('out')
    expect(cellKindOf({}, 'section')).toBe('sectional')
    expect(cellKindOf({}, 'block')).toBeNull()
    expect(cellKindOf(null, null)).toBeNull()
  })

  it('подписи видов ячеек', () => {
    expect(CELL_KIND_TITLES).toEqual({ in: 'вводная', out: 'отходящая', sectional: 'секционная' })
    expect(cellKindTitle('in')).toBe('вводная')
    expect(cellKindTitle(null)).toBe('')
  })

  it('номер из имени ячейки', () => {
    expect(cellNumberFromName('Яч. №1 (Вводная)')).toBe(1)
    expect(cellNumberFromName('Яч. №34 (Отходящая)')).toBe(34)
    expect(cellNumberFromName('Вводной разъединитель')).toBeNull()
    expect(cellNumberFromName(null)).toBeNull()
  })

  it('склонение подписей: 1 ячейка / 2 ячейки / 5 ячеек', () => {
    expect(cellsLabel(1)).toBe('1 ячейка')
    expect(cellsLabel(2)).toBe('2 ячейки')
    expect(cellsLabel(4)).toBe('4 ячейки')
    expect(cellsLabel(5)).toBe('5 ячеек')
    expect(cellsLabel(6)).toBe('6 ячеек')
    expect(cellsLabel(11)).toBe('11 ячеек')
    expect(cellsLabel(21)).toBe('21 ячейка')
    expect(cellsLabel(34)).toBe('34 ячейки')
    expect(elementsLabel(1)).toBe('1 элемент')
    expect(elementsLabel(3)).toBe('3 элемента')
    expect(elementsLabel(6)).toBe('6 элементов')
    expect(pluralRu(0, ['а', 'б', 'в'])).toBe('в')
  })
})
