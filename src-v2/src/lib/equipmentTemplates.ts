/**
 * Шаблоны составных устройств (этап 2 модели оборудования «Карьер»).
 *
 * `gis.asset_types.composite_template` в v2 — это **массив**:
 * первый элемент — метаданные (`version: 2, profile, title, configurable,
 * cells_per_section, disconnector`), дальше по элементу на секцию с упорядоченным
 * списком ячеек `{cell_kind: in|out|sectional, count, label, voltage_kv}`.
 *
 * Здесь только чистые функции разбора/предпросмотра: мастер «По шаблону» в
 * редакторе схемы показывает ровно то, что создаст `POST /api/schema/composite`
 * (backend строит раскладку той же логикой `build_layout`). Модуль проверяют
 * unit-тесты `equipmentTemplates.test.ts`.
 */

export type CellKind = 'in' | 'out' | 'sectional'

export const CELL_KIND_TITLES: Record<CellKind, string> = {
  in: 'вводная',
  out: 'отходящая',
  sectional: 'секционная',
}

/** Старая роль элемента схемы (`schema_role`) → вид ячейки. */
export const CELL_KIND_BY_ROLE: Record<string, CellKind> = {
  in: 'in',
  incoming: 'in',
  out: 'out',
  outgoing: 'out',
  sectional: 'sectional',
  section: 'sectional',
  cell: 'out',
}

export const CELL_KINDS: readonly CellKind[] = ['in', 'out', 'sectional']

/** Границы параметра «Ячеек на секцию» (совпадают с Pydantic `ge=1, le=50`). */
export const MIN_CELLS_PER_SECTION = 1
export const MAX_CELLS_PER_SECTION = 50
export const PS_DEFAULT_CELLS = 17

/** Известные профили составных устройств. */
export type CompositeProfile = 'bkru' | 'ps_35_6' | 'ktp'

export interface TemplateCellSpec {
  cell_kind: CellKind
  count: number
  label: string
  voltage_kv: number | null
  type_code: string | null
}

export interface TemplateSectionSpec {
  section_no: number
  label: string
  voltage_kv: number | null
  cells: TemplateCellSpec[]
}

export interface TemplateDisconnectorSpec {
  cell_kind: CellKind
  type_code: string | null
  label: string
  voltage_kv: number | null
}

export interface CompositeTemplate {
  /** Шаблон v2 (секции/вводные/секционные); legacy v1 сюда не попадает. */
  isV2: boolean
  profile: CompositeProfile | string | null
  title: string | null
  /** ПС: можно задать «Ячеек на секцию». */
  configurable: boolean
  /** Значение по умолчанию для настраиваемого шаблона (17 у ПС). */
  cellsPerSection: number | null
  sections: TemplateSectionSpec[]
  /** КТП: ячеек нет, только вводной разъединитель. */
  disconnector: TemplateDisconnectorSpec | null
  /** Сколько ячеек создаст шаблон при настройках по умолчанию. */
  totalCells: number
}

export const EMPTY_TEMPLATE: CompositeTemplate = {
  isV2: false,
  profile: null,
  title: null,
  configurable: false,
  cellsPerSection: null,
  sections: [],
  disconnector: null,
  totalCells: 0,
}

function asNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function normalizeKind(raw: unknown): CellKind {
  const value = String(raw ?? '').trim().toLowerCase()
  if ((CELL_KINDS as readonly string[]).includes(value)) return value as CellKind
  return CELL_KIND_BY_ROLE[value] ?? 'out'
}

function normalizeCell(raw: unknown): TemplateCellSpec | null {
  if (!raw || typeof raw !== 'object') return null
  const entry = raw as Record<string, unknown>
  const kind = normalizeKind(entry.cell_kind ?? entry.kind)
  const count = Math.max(1, Math.min(200, Math.trunc(asNumber(entry.count) ?? 1)))
  const label = String(entry.label ?? '').trim() || CELL_KIND_TITLES[kind]
  const typeCode = entry.type_code ? String(entry.type_code) : null
  return {
    cell_kind: kind,
    count,
    label,
    voltage_kv: asNumber(entry.voltage_kv),
    type_code: typeCode,
  }
}

/** Элемент-метаданные: у секции `cells` — список, у меты — число/ключа нет. */
function isMetaEntry(entry: Record<string, unknown>): boolean {
  if ('section_no' in entry || 'type_code' in entry) return false
  return !Array.isArray(entry.cells)
}

function normalizeDisconnector(raw: unknown): TemplateDisconnectorSpec | null {
  if (!raw || typeof raw !== 'object') return null
  const entry = raw as Record<string, unknown>
  return {
    cell_kind: normalizeKind(entry.cell_kind ?? 'in'),
    type_code: entry.type_code ? String(entry.type_code) : null,
    label: String(entry.label ?? '').trim() || 'Вводной разъединитель',
    voltage_kv: asNumber(entry.voltage_kv),
  }
}

/** Итог по секциям без настройки (значения из шаблона как есть). */
function countCells(sections: TemplateSectionSpec[]): number {
  return sections.reduce(
    (total, section) => total + section.cells.reduce((sum, cell) => sum + cell.count, 0),
    0,
  )
}

/**
 * Разобрать `composite_template` (v2-массив, dict плана 31 или legacy v1).
 * Legacy v1 не считается шаблоном этапа 2 — мастер «По шаблону» его не предлагает.
 */
export function parseCompositeTemplate(raw: unknown): CompositeTemplate {
  if (Array.isArray(raw)) {
    const entries = raw.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    if (entries.length === 0) return { ...EMPTY_TEMPLATE }
    const first = entries[0]
    const hasV2 = isMetaEntry(first) && (first.version != null || first.profile != null || first.configurable != null)
    if (!hasV2 && !entries.some((entry) => Array.isArray(entry.cells))) {
      return { ...EMPTY_TEMPLATE }
    }
    const meta = isMetaEntry(first) ? first : {}
    const sections: TemplateSectionSpec[] = []
    entries.forEach((entry, index) => {
      if (isMetaEntry(entry)) return
      const rawCells = Array.isArray(entry.cells) ? entry.cells : []
      const cells = rawCells.map(normalizeCell).filter((cell): cell is TemplateCellSpec => cell !== null)
      if (cells.length === 0) return
      sections.push({
        section_no: Math.trunc(asNumber(entry.section_no) ?? index + 1),
        label: String(entry.label ?? '').trim() || `Секция ${index + 1}`,
        voltage_kv: asNumber(entry.voltage_kv),
        cells,
      })
    })
    const disconnector = normalizeDisconnector(meta.disconnector)
    const totalCells = countCells(sections)
    return {
      isV2: true,
      profile: meta.profile ? String(meta.profile) : null,
      title: meta.title ? String(meta.title) : null,
      configurable: Boolean(meta.configurable),
      cellsPerSection: asNumber(meta.cells_per_section),
      sections,
      disconnector,
      totalCells,
    }
  }

  if (raw && typeof raw === 'object') {
    // Формат плана 31 §3.5: {"sections": [...], "cells": [...], "disconnector": {...}}.
    const dict = raw as Record<string, unknown>
    const rawSections = Array.isArray(dict.sections) ? dict.sections : []
    const topCells = Array.isArray(dict.cells) ? dict.cells : []
    const sections: TemplateSectionSpec[] = []
    if (rawSections.length > 0) {
      rawSections.forEach((item, index) => {
        if (!item || typeof item !== 'object') return
        const entry = item as Record<string, unknown>
        const own = Array.isArray(entry.cells) && entry.cells.length > 0 ? entry.cells : topCells
        const cells = own.map(normalizeCell).filter((cell): cell is TemplateCellSpec => cell !== null)
        if (cells.length === 0) return
        sections.push({
          section_no: Math.trunc(asNumber(entry.no ?? entry.section_no) ?? index + 1),
          label: String(entry.label ?? '').trim() || `Секция ${index + 1}`,
          voltage_kv: asNumber(entry.voltage_kv),
          cells,
        })
      })
    } else if (topCells.length > 0) {
      const cells = topCells.map(normalizeCell).filter((cell): cell is TemplateCellSpec => cell !== null)
      if (cells.length > 0) {
        sections.push({ section_no: 1, label: 'Секция 1', voltage_kv: null, cells })
      }
    }
    const disconnector = normalizeDisconnector(dict.disconnector)
    if (sections.length === 0 && disconnector === null) return { ...EMPTY_TEMPLATE }
    return {
      isV2: true,
      profile: dict.profile ? String(dict.profile) : null,
      title: dict.title ? String(dict.title) : null,
      configurable: Boolean(dict.configurable),
      cellsPerSection: asNumber(dict.cells_per_section),
      sections,
      disconnector,
      totalCells: countCells(sections),
    }
  }

  return { ...EMPTY_TEMPLATE }
}

/** Профиль по коду/названию типа — копия правила backend `profile_for_type`. */
export function profileForType(code: string | null | undefined, name: string | null | undefined): CompositeProfile | null {
  const codeNorm = (code ?? '').trim().toLowerCase()
  const nameNorm = (name ?? '').trim().toLowerCase()
  const bkru = ['bkru', 'bkru_1', 'bkru_2', 'bkru_bkru', 'bkru_standard']
  const ktp = ['ktp', 'ktp_1', 'ktp_2']
  const ps = ['ps_35', 'ps_35_6_kv', 'ps_35_6_kv_2', 'ps_35_6', 'substation', 'tps']
  if (bkru.includes(codeNorm) || nameNorm.includes('бкру')) return 'bkru'
  // КТП проверяется раньше ПС: «комплектная трансформаторная подстанция» содержит «подстанц».
  if (ktp.includes(codeNorm) || nameNorm.includes('ктп')) return 'ktp'
  if (
    ps.includes(codeNorm) ||
    nameNorm.includes('пс-') ||
    nameNorm.includes('пс ') ||
    nameNorm.includes('подстанц')
  ) {
    return 'ps_35_6'
  }
  return null
}

/** Состав секции ПС: 1 вводная + (n−2) отходящих + 1 секционная (n ≥ 2). */
export function psSectionCells(cellsPerSection: number): Array<{ cell_kind: CellKind; count: number }> {
  const perSection = Math.trunc(cellsPerSection)
  if (perSection <= 1) return [{ cell_kind: 'in', count: 1 }]
  return [
    { cell_kind: 'in', count: 1 },
    { cell_kind: 'out', count: perSection - 2 },
    { cell_kind: 'sectional', count: 1 },
  ]
}

/**
 * Встроенный шаблон профиля — зеркало backend `builtin_template`.
 * Нужен, если тип ещё не размечен миграцией: мастер всё равно показывает
 * БКРУ (6), ПС 35/6 (17×2) и КТП (разъединитель).
 */
export function builtinTemplate(profile: CompositeProfile): CompositeTemplate {
  if (profile === 'bkru') {
    return {
      isV2: true,
      profile,
      title: 'БКРУ (6 ячеек)',
      configurable: false,
      cellsPerSection: null,
      sections: [
        {
          section_no: 1,
          label: 'Секция 1',
          voltage_kv: 6,
          cells: [
            { cell_kind: 'in', count: 1, label: CELL_KIND_TITLES.in, voltage_kv: 6, type_code: null },
            { cell_kind: 'out', count: 2, label: CELL_KIND_TITLES.out, voltage_kv: 6, type_code: null },
            { cell_kind: 'sectional', count: 1, label: CELL_KIND_TITLES.sectional, voltage_kv: 6, type_code: null },
          ],
        },
        {
          section_no: 2,
          label: 'Секция 2',
          voltage_kv: 6,
          cells: [
            { cell_kind: 'out', count: 1, label: CELL_KIND_TITLES.out, voltage_kv: 6, type_code: null },
            { cell_kind: 'in', count: 1, label: CELL_KIND_TITLES.in, voltage_kv: 6, type_code: null },
          ],
        },
      ],
      disconnector: null,
      totalCells: 6,
    }
  }

  if (profile === 'ps_35_6') {
    const sections: TemplateSectionSpec[] = [
      { section_no: 1, label: 'Секция 1 (35 кВ)', voltage_kv: 35 },
      { section_no: 2, label: 'Секция 2 (6 кВ)', voltage_kv: 6 },
    ].map((section) => ({
      ...section,
      cells: psSectionCells(PS_DEFAULT_CELLS).map((cell) => ({
        cell_kind: cell.cell_kind,
        count: cell.count,
        label: CELL_KIND_TITLES[cell.cell_kind],
        voltage_kv: section.voltage_kv,
        type_code: null,
      })),
    }))
    return {
      isV2: true,
      profile,
      title: 'ПС 35/6 кВ (17 ячеек на секцию)',
      configurable: true,
      cellsPerSection: PS_DEFAULT_CELLS,
      sections,
      disconnector: null,
      totalCells: countCells(sections),
    }
  }

  return {
    isV2: true,
    profile: 'ktp',
    title: 'КТП (без ячеек, вводной разъединитель)',
    configurable: false,
    cellsPerSection: null,
    sections: [],
    disconnector: {
      cell_kind: 'in',
      type_code: 'razedinitel',
      label: 'Вводной разъединитель',
      voltage_kv: 6,
    },
    totalCells: 0,
  }
}

/** Разобрать шаблон типа: v2 из API → встроенный профиль по коду/названию. */
export function templateForType(type: {
  code?: string | null
  name?: string | null
  composite_template?: unknown
}): CompositeTemplate {
  const parsed = parseCompositeTemplate(type.composite_template)
  if (parsed.isV2 && (parsed.sections.length > 0 || parsed.disconnector)) return parsed
  const profile = profileForType(type.code, type.name)
  return profile ? builtinTemplate(profile) : { ...EMPTY_TEMPLATE }
}

export interface SectionPreviewCell {
  cell_kind: CellKind
  count: number
}

export interface SectionPreview {
  section_no: number
  label: string
  voltage_kv: number | null
  cells: SectionPreviewCell[]
  total: number
}

/**
 * Предпросмотр состава: что именно создаст backend.
 * Для настраиваемого ПС секции пересобираются под `cellsPerSection`
 * (ровно n ячеек на секцию), остальные шаблоны не меняются.
 */
export function buildSectionPreview(
  template: CompositeTemplate,
  cellsPerSection?: number | null,
): SectionPreview[] {
  const perSection =
    template.configurable && cellsPerSection != null && Number.isFinite(cellsPerSection)
      ? Math.trunc(cellsPerSection)
      : null

  return template.sections.map((section) => {
    let cells: SectionPreviewCell[]
    if (perSection !== null && template.profile === 'ps_35_6') {
      cells = psSectionCells(perSection)
    } else {
      cells = section.cells.map((cell) => ({ cell_kind: cell.cell_kind, count: cell.count }))
    }
    return {
      section_no: section.section_no,
      label: section.label,
      voltage_kv: section.voltage_kv,
      cells,
      total: cells.reduce((sum, cell) => sum + cell.count, 0),
    }
  })
}

/** Всего ячеек в предпросмотре + вводной разъединитель (КТП). */
export function previewTotals(
  template: CompositeTemplate,
  cellsPerSection?: number | null,
): { cells: number; sections: number; hasDisconnector: boolean; children: number } {
  const preview = buildSectionPreview(template, cellsPerSection)
  const cells = preview.reduce((sum, section) => sum + section.total, 0)
  const hasDisconnector = template.disconnector !== null
  return {
    cells,
    sections: preview.length,
    hasDisconnector,
    children: cells + (hasDisconnector ? 1 : 0),
  }
}

/** Проверка «Ячеек на секцию»: целое 1…50 (как Pydantic `ge=1, le=50`). */
export function validateCellsPerSection(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined || String(value).trim() === '') {
    return 'Укажите число ячеек на секцию'
  }
  const parsed = Number(String(value).replace(',', '.'))
  if (!Number.isFinite(parsed)) return 'Число ячеек должно быть числом'
  if (!Number.isInteger(parsed)) return 'Число ячеек должно быть целым'
  if (parsed < MIN_CELLS_PER_SECTION || parsed > MAX_CELLS_PER_SECTION) {
    return `Допустимо от ${MIN_CELLS_PER_SECTION} до ${MAX_CELLS_PER_SECTION} ячеек на секцию`
  }
  return null
}

/** Короткая подпись шаблона для карточки мастера. */
export function templateSummary(template: CompositeTemplate, cellsPerSection?: number | null): string {
  const totals = previewTotals(template, cellsPerSection)
  if (totals.cells === 0 && totals.hasDisconnector) {
    return '0 ячеек · вводной разъединитель'
  }
  const sectionsText = totals.sections > 1 ? `${totals.sections} секции · ` : ''
  const disconnectorText = totals.hasDisconnector ? ' + вводной разъединитель' : ''
  return `${sectionsText}${totals.cells} ячеек${disconnectorText}`
}

/** Название шаблона: из меты API, иначе человеческое имя профиля. */
export function templateTitle(template: CompositeTemplate, fallback = ''): string {
  if (template.title) return template.title
  if (template.profile === 'bkru') return 'БКРУ (6 ячеек)'
  if (template.profile === 'ps_35_6') return 'ПС 35/6 кВ'
  if (template.profile === 'ktp') return 'КТП (без ячеек, вводной разъединитель)'
  return fallback
}

/** Вид ячейки по `params` схемы (block children) или по старой роли. */
export function cellKindOf(
  params: Record<string, unknown> | null | undefined,
  role?: string | null,
): CellKind | null {
  const raw = params?.cell_kind
  if (raw != null) {
    const normalized = normalizeKind(raw)
    if ((CELL_KINDS as readonly string[]).includes(String(raw))) return normalized
  }
  if (role) return CELL_KIND_BY_ROLE[String(role).toLowerCase()] ?? null
  return null
}

/** Подпись вида ячейки: «вводная» / «отходящая» / «секционная». */
export function cellKindTitle(kind: CellKind | null | undefined): string {
  return kind ? CELL_KIND_TITLES[kind] : ''
}

/** Номер ячейки из имени «Яч. №12 (Отходящая)» — для бейджа на схеме. */
export function cellNumberFromName(name: string | null | undefined): number | null {
  if (!name) return null
  const match = /№\s*(\d+)/.exec(name)
  if (!match) return null
  const parsed = Number(match[1])
  return Number.isFinite(parsed) ? parsed : null
}

/** Русское склонение по числу: 1 ячейка, 2 ячейки, 5 ячеек. */
export function pluralRu(count: number, forms: [string, string, string]): string {
  const value = Math.abs(Math.trunc(count))
  const mod100 = value % 100
  const mod10 = value % 10
  if (mod100 >= 11 && mod100 <= 14) return forms[2]
  if (mod10 === 1) return forms[0]
  if (mod10 >= 2 && mod10 <= 4) return forms[1]
  return forms[2]
}

/** Подпись «N ячеек» с правильным склонением. */
export function cellsLabel(count: number): string {
  return `${count} ${pluralRu(count, ['ячейка', 'ячейки', 'ячеек'])}`
}

/** Подпись «N элементов» (блок/контур). */
export function elementsLabel(count: number): string {
  return `${count} ${pluralRu(count, ['элемент', 'элемента', 'элементов'])}`
}
