/**
 * Поля паспорта типа оборудования и группы классов (этап 1 модели «Карьер»).
 *
 * Источник правды — `gis.asset_type_fields` (backend миграции 0015), их отдаёт
 * `GET /api/asset-types?with_fields=1`. Здесь только чистые функции: раскладка
 * типов по вкладкам классов, нормализация полей, стартовые значения, клиентская
 * проверка и сборка `attrs` для `POST /api/assets`, а также разбор серверного
 * 422 (`fields` + `field_labels`) на ошибки конкретных полей формы.
 *
 * Модуль намеренно не зависит от React — его проверяют unit-тесты
 * `assetFields.test.ts` на реальных ответах API.
 */

import type { AssetFieldDataType, AssetType, AssetTypeField } from './gis'

export type AttrValues = Record<string, string>
export type FieldErrors = Record<string, string>

// --- группы классов --------------------------------------------------------

export interface EquipmentGroup {
  /** `equipment_class` в API. */
  code: string
  /** `group_code` в API (код вкладки, этап 2). */
  groupCode: string
  /** Понятное русское название вкладки. */
  title: string
  icon: string
}

/** Вкладки в том порядке, в котором их видит админ. */
export const EQUIPMENT_GROUPS: readonly EquipmentGroup[] = [
  { code: 'distribution', groupCode: 'distribution', title: 'Распредустройства', icon: '🏭' },
  { code: 'transformer_assembly', groupCode: 'transformers', title: 'Трансформаторы и сборки', icon: '⚡' },
  { code: 'switching', groupCode: 'switching', title: 'Коммутационные', icon: '🔌' },
  { code: 'cell', groupCode: 'cells', title: 'Ячейки', icon: '🔲' },
  { code: 'cable', groupCode: 'cables', title: 'Кабели', icon: '🧵' },
  { code: 'mobile', groupCode: 'mobile', title: 'Мобильное', icon: '🚜' },
  { code: 'line', groupCode: 'lines', title: 'Опоры', icon: '🗼' },
  { code: 'source', groupCode: 'sources', title: 'Источники', icon: '🔋' },
] as const

/** Запасная вкладка: тип без класса (или старый API без `equipment_class`). */
export const OTHER_GROUP: EquipmentGroup = {
  code: 'equipment',
  groupCode: 'other',
  title: 'Прочее',
  icon: '📦',
}

const GROUP_BY_CLASS = new Map<string, EquipmentGroup>(
  EQUIPMENT_GROUPS.map((group) => [group.code, group]),
)
const GROUP_BY_GROUP_CODE = new Map<string, EquipmentGroup>(
  [...EQUIPMENT_GROUPS, OTHER_GROUP].map((group) => [group.groupCode, group]),
)

/** Совместимость со старым API без `equipment_class` (категория → ближайшая вкладка). */
const CLASS_BY_CATEGORY: Record<string, string> = {
  source: 'source',
  line: 'line',
  pole: 'line',
  mobile: 'mobile',
  lighting: 'mobile',
  aux: 'mobile',
  equipment: 'equipment',
}

/** Вкладка типа: по `equipment_class`, затем по `group_code`, затем по категории. */
export function groupOfType(type: AssetType): EquipmentGroup {
  const equipmentClass = (type.equipment_class || '').trim()
  const byClass = equipmentClass ? GROUP_BY_CLASS.get(equipmentClass) : undefined
  if (byClass) return byClass
  const groupCode = (type.group_code || '').trim()
  const byGroupCode = groupCode ? GROUP_BY_GROUP_CODE.get(groupCode) : undefined
  if (byGroupCode) return byGroupCode
  return GROUP_BY_CLASS.get(CLASS_BY_CATEGORY[type.category] ?? '') ?? OTHER_GROUP
}

export interface TypeGroup {
  group: EquipmentGroup
  types: AssetType[]
}

/**
 * Разложить типы по вкладкам классов в утверждённом порядке (пустые не показываем).
 * Порядок типов внутри вкладки — как пришёл от API (`sort_order`, `name`).
 */
export function groupTypes(types: AssetType[]): TypeGroup[] {
  const buckets = new Map<string, TypeGroup>()
  for (const type of types) {
    const group = groupOfType(type)
    const bucket = buckets.get(group.code)
    if (bucket) bucket.types.push(type)
    else buckets.set(group.code, { group, types: [type] })
  }
  const ordered: TypeGroup[] = []
  for (const group of EQUIPMENT_GROUPS) {
    const bucket = buckets.get(group.code)
    if (bucket) ordered.push(bucket)
  }
  const other = buckets.get(OTHER_GROUP.code)
  if (other) ordered.push(other)
  return ordered
}

/** Плоский список типов вкладки (для селекта «модель»); `classCode` — `equipment_class`. */
export function typesOfGroup(groups: TypeGroup[], classCode: string): AssetType[] {
  return groups.find((item) => item.group.code === classCode)?.types ?? []
}

// --- нормализация полей ----------------------------------------------------

const KNOWN_DATA_TYPES: readonly AssetFieldDataType[] = [
  'number',
  'integer',
  'text',
  'boolean',
  'date',
  'select',
]

/** Старый `attr_schema.type` → `data_type` таблицы полей. */
const LEGACY_DATA_TYPES: Record<string, AssetFieldDataType> = {
  number: 'number',
  integer: 'integer',
  boolean: 'boolean',
  date: 'date',
  select: 'select',
  string: 'text',
  text: 'text',
}

export function normalizeDataType(raw: unknown): AssetFieldDataType {
  const value = String(raw ?? '').trim().toLowerCase()
  if ((KNOWN_DATA_TYPES as readonly string[]).includes(value)) return value as AssetFieldDataType
  return LEGACY_DATA_TYPES[value] ?? 'text'
}

/** Подписи и единицы известных полей — только для аварийного пути без таблицы полей. */
const FIELD_META: Record<string, { label: string; unit?: string; group?: string }> = {
  power_kw: { label: 'Мощность', unit: 'кВт', group: 'Мощность' },
  power_kva: { label: 'Полная мощность', unit: 'кВ·А', group: 'Мощность' },
  voltage_in_kv: { label: 'Напряжение на входе', unit: 'кВ', group: 'Напряжение' },
  voltage_out_kv: { label: 'Напряжение на выходе', unit: 'кВ', group: 'Напряжение' },
  voltage_kv: { label: 'Напряжение', unit: 'кВ', group: 'Напряжение' },
  drive_type: { label: 'Тип привода', group: 'Исполнение' },
  fuel_type: { label: 'Тип топлива', group: 'Исполнение' },
  bucket_m3: { label: 'Объём ковша', unit: 'м³', group: 'Основные' },
  section_breaker: { label: 'Секционный выключатель', group: 'Основные' },
  cable_mark: { label: 'Марка кабеля', group: 'Кабель' },
  section_mm2: { label: 'Сечение', unit: 'мм²', group: 'Кабель' },
  length_m: { label: 'Длина', unit: 'м', group: 'Кабель' },
  lifecycle_status: { label: 'Состояние кабеля', group: 'Кабель' },
  serial_no: { label: 'Заводской номер', group: 'Паспорт' },
  manufacturer: { label: 'Изготовитель', group: 'Паспорт' },
  model: { label: 'Модель', group: 'Паспорт' },
  commissioned_on: { label: 'Дата ввода', group: 'Паспорт' },
}

/** `power_kw` → `Power kw` (как `humanize_code` на backend). */
export function humanizeCode(code: string): string {
  const words = code.replace(/[_-]+/g, ' ').trim()
  return words ? words[0].toUpperCase() + words.slice(1) : code
}

function asNumberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function asOptions(value: unknown): Array<string | number | boolean> {
  return Array.isArray(value) ? (value as Array<string | number | boolean>) : []
}

function normalizeField(field: AssetTypeField): AssetTypeField {
  return {
    ...field,
    label: field.label?.trim() || humanizeCode(field.code),
    data_type: normalizeDataType(field.data_type),
    required: Boolean(field.required),
    options: asOptions(field.options),
    unit: field.unit ?? null,
    group_label: field.group_label ?? null,
    min: asNumberOrNull(field.min),
    max: asNumberOrNull(field.max),
    sort_order: field.sort_order ?? 0,
  }
}

/**
 * Поля типа для формы.
 *
 * Основной путь — `type.fields` из `with_fields=1`. Если старый backend поля не
 * отдал (или таблица ещё пуста), они выводятся из `attr_schema`/`required_attrs`
 * тем же порядком, что и мигратор: обязательные первыми, дальше по алфавиту.
 */
export function typeFields(type: AssetType): AssetTypeField[] {
  const fromApi = Array.isArray(type.fields) ? type.fields : []
  if (fromApi.length > 0) {
    return fromApi
      .map(normalizeField)
      .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.code.localeCompare(b.code))
  }

  const schema = (type.attr_schema ?? {}) as Record<string, Record<string, unknown>>
  const required = new Set((type.required_attrs ?? []).map(String))
  const codes = Array.from(new Set([...Object.keys(schema), ...required])).sort((a, b) => {
    const requiredDelta = Number(required.has(b)) - Number(required.has(a))
    return requiredDelta || a.localeCompare(b)
  })

  return codes.map((code, index) => {
    const rule = schema[code] ?? {}
    const meta = FIELD_META[code] ?? { label: humanizeCode(code) }
    return normalizeField({
      code,
      label: String(rule.label ?? meta.label),
      unit: (rule.unit as string | undefined) ?? meta.unit ?? null,
      data_type: normalizeDataType(rule.data_type ?? rule.type),
      required: required.has(code),
      default_value: rule.default ?? rule.default_value ?? null,
      options: asOptions(rule.options),
      min: asNumberOrNull(rule.min ?? rule.minimum),
      max: asNumberOrNull(rule.max ?? rule.maximum),
      group_label: (rule.group_label as string | undefined) ?? meta.group ?? null,
      sort_order: (index + 1) * 10,
    })
  })
}

export interface FieldSection {
  label: string
  fields: AssetTypeField[]
}

/** Сгруппировать поля по `group_label` для секций формы. */
export function groupFields(fields: AssetTypeField[]): FieldSection[] {
  const sections: FieldSection[] = []
  for (const field of fields) {
    const label = field.group_label?.trim() || 'Основные'
    const section = sections.find((item) => item.label === label)
    if (section) section.fields.push(field)
    else sections.push({ label, fields: [field] })
  }
  return sections
}

// --- значения формы --------------------------------------------------------

function defaultToFormValue(field: AssetTypeField): string {
  const value = field.default_value
  if (value === null || value === undefined) return ''
  if (field.data_type === 'boolean') return value === true || value === 'true' ? 'true' : 'false'
  return String(value)
}

/** Стартовые значения формы из `default_value` обязательных/необязательных полей. */
export function defaultAttrValues(fields: AssetTypeField[]): AttrValues {
  const values: AttrValues = {}
  for (const field of fields) {
    const value = defaultToFormValue(field)
    if (value) values[field.code] = value
  }
  return values
}

export function isAttrEmpty(value: string | undefined | null): boolean {
  return !String(value ?? '').trim()
}

/** Число из поля ввода: «1250,5» → 1250.5, «1 250» → 1250. */
export function parseNumericInput(value: string): number {
  const cleaned = String(value ?? '')
    .replace(/\s+/g, '')
    .replace(',', '.')
  return Number(cleaned)
}

function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const parsed = new Date(`${value}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return false
  return parsed.toISOString().slice(0, 10) === value
}

/** Проверить одно значение по описанию поля; вернуть русское сообщение или null. */
export function checkFieldValue(field: AssetTypeField, rawValue: string): string | null {
  const value = rawValue.trim()
  if (!value) return null
  const options = field.options ?? []

  switch (field.data_type) {
    case 'number':
    case 'integer': {
      const number = parseNumericInput(value)
      if (!Number.isFinite(number)) {
        return field.data_type === 'integer' ? 'Ожидается целое число' : 'Ожидается число'
      }
      if (field.data_type === 'integer' && !Number.isInteger(number)) return 'Ожидается целое число'
      if (field.min !== null && field.min !== undefined && number < field.min) {
        return `Значение меньше минимального (${field.min})`
      }
      if (field.max !== null && field.max !== undefined && number > field.max) {
        return `Значение больше максимального (${field.max})`
      }
      return null
    }
    case 'boolean':
      return value === 'true' || value === 'false' ? null : 'Ожидается да/нет'
    case 'date':
      return isIsoDate(value) ? null : 'Ожидается дата в формате ГГГГ-ММ-ДД'
    case 'select': {
      if (options.length === 0) return null
      const allowed = options.map((option) => String(option))
      return allowed.includes(value) ? null : `Недопустимое значение (допустимо: ${allowed.join(', ')})`
    }
    default:
      return null
  }
}

/**
 * Клиентская проверка перед отправкой: обязательность, типы, `min`/`max`,
 * допустимые значения списка. Сообщения совпадают с backend, чтобы админ видел
 * одинаковый текст до и после запроса.
 */
export function validateAssetFields(fields: AssetTypeField[], values: AttrValues): FieldErrors {
  const errors: FieldErrors = {}
  for (const field of fields) {
    const rawValue = values[field.code] ?? ''
    if (isAttrEmpty(rawValue)) {
      if (field.required) errors[field.code] = 'Обязательное поле'
      continue
    }
    const message = checkFieldValue(field, rawValue)
    if (message) errors[field.code] = message
  }
  return errors
}

/** Подписи пропущенных обязательных полей (для сводки над формой). */
export function missingRequiredLabels(fields: AssetTypeField[], values: AttrValues): string[] {
  return fields
    .filter((field) => field.required && isAttrEmpty(values[field.code]))
    .map((field) => field.label)
}

/** Собрать `attrs` из значений формы: числа/целые — числами, да/нет — boolean. */
export function buildAttrs(fields: AssetTypeField[], values: AttrValues): Record<string, unknown> {
  const attrs: Record<string, unknown> = {}
  for (const field of fields) {
    const rawValue = (values[field.code] ?? '').trim()
    if (!rawValue) continue
    if (field.data_type === 'number') attrs[field.code] = parseNumericInput(rawValue)
    else if (field.data_type === 'integer') attrs[field.code] = Math.trunc(parseNumericInput(rawValue))
    else if (field.data_type === 'boolean') attrs[field.code] = rawValue === 'true'
    else attrs[field.code] = rawValue
  }
  return attrs
}

// --- разбор серверной ошибки 422 -------------------------------------------

/** Подписи основных (не паспортных) полей формы создания объекта. */
const BASE_FIELD_LABELS: Record<string, string> = {
  name: 'Название',
  code: 'Код',
  type_code: 'Тип',
  status: 'Состояние',
  location_text: 'Расположение',
  parent_id: 'Родительский объект',
  x: 'X',
  y: 'Y',
  attrs: 'Поля паспорта',
  lifecycle_status: 'Состояние кабеля',
  cell_kind: 'Тип ячейки',
  cell_no: 'Номер ячейки',
  section_no: 'Номер секции',
}

export interface ServerErrorMapping {
  /** Ошибки полей паспорта: код поля → сообщение. */
  attrs: FieldErrors
  /** Ошибки основных полей формы: имя/код/тип/координаты… */
  base: FieldErrors
  /** Русские подписи для всех распознанных ключей. */
  labels: Record<string, string>
  /** Ключи, которые не удалось сопоставить с полем формы (с текстом ошибки). */
  unmatched: string[]
  /** Готовая сводка для предупреждения над формой — всегда с пояснением. */
  summary: string
}

function labelOf(fields: AssetTypeField[], code: string): string {
  return fields.find((field) => field.code === code)?.label ?? FIELD_META[code]?.label ?? humanizeCode(code)
}

/**
 * Разобрать `fields`/`field_labels` ответа 422 на ошибки конкретных полей.
 *
 * Ключи могут быть как кодом поля паспорта (`cable_mark`), так и путём до него
 * (`attrs.cable_mark`) или основным полем (`name`, `type_code`, `x`…). Подписи
 * берём из `field_labels`, затем из описания поля типа, затем из словаря формы —
 * поэтому под полем всегда русский текст, а не машинный ключ.
 */
export function mapServerFieldErrors(
  fields: AssetTypeField[],
  serverFields: Record<string, string>,
  serverLabels: Record<string, string> = {},
): ServerErrorMapping {
  const attrCodes = new Set(fields.map((field) => field.code))
  const result: ServerErrorMapping = { attrs: {}, base: {}, labels: {}, unmatched: [], summary: '' }

  for (const [key, message] of Object.entries(serverFields ?? {})) {
    const tail = key.includes('.') ? key.slice(key.lastIndexOf('.') + 1) : key
    if (attrCodes.has(key)) {
      result.attrs[key] = message
      result.labels[key] = serverLabels[key] || labelOf(fields, key)
    } else if (attrCodes.has(tail)) {
      result.attrs[tail] = message
      result.labels[tail] = serverLabels[key] || labelOf(fields, tail)
    } else if (!key.includes('.') && BASE_FIELD_LABELS[key]) {
      result.base[key] = message
      result.labels[key] = serverLabels[key] || BASE_FIELD_LABELS[key]
    } else {
      const label = serverLabels[key] || BASE_FIELD_LABELS[tail] || labelOf(fields, tail) || key
      result.unmatched.push(`${label}: ${message}`)
    }
  }

  const parts: string[] = []
  const attrLabels = Object.keys(result.attrs).map((code) => result.labels[code] ?? code)
  if (attrLabels.length > 0) parts.push(`поля паспорта — ${attrLabels.join(', ')}`)
  const baseLabels = Object.keys(result.base).map((key) => result.labels[key] ?? key)
  if (baseLabels.length > 0) parts.push(`основные поля — ${baseLabels.join(', ')}`)
  if (result.unmatched.length > 0) parts.push(result.unmatched.join('; '))
  result.summary = parts.length > 0 ? `Проверьте: ${parts.join('; ')}` : ''
  return result
}

/** Подписи значений списков, которые понятны человеку без кода. */
export const OPTION_LABELS: Record<string, Record<string, string>> = {
  lifecycle_status: {
    installed: 'на оборудовании',
    reserve: 'в запасе',
    repair: 'в ремонте',
  },
}

/** Подпись значения `select` с русским переводом, если он известен. */
export function optionLabel(fieldCode: string, option: string | number | boolean): string {
  const value = String(option)
  return OPTION_LABELS[fieldCode]?.[value] ?? value
}

export type CableLifecycleStatus = 'installed' | 'reserve' | 'repair'

/**
 * Значение «Состояния кабеля» для отдельной колонки `gis.assets.lifecycle_status`
 * (миграция 0015). Возвращает null, если поле типу не принадлежит или значение
 * не из CHECK-списка — тогда backend поставит `installed` сам.
 */
export function cableLifecycleStatus(
  fields: AssetTypeField[],
  values: AttrValues,
): CableLifecycleStatus | null {
  if (!fields.some((field) => field.code === 'lifecycle_status')) return null
  const value = (values.lifecycle_status ?? '').trim()
  return value === 'installed' || value === 'reserve' || value === 'repair' ? value : null
}
