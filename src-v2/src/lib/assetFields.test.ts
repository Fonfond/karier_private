/**
 * Тесты динамической формы создания объекта (этап 1 модели «Карьер»).
 *
 * Фикстуры взяты из реальных ответов API:
 *  - поля типа `cable` — `GET /api/asset-types?with_fields=1` на `karier_test_db`
 *    после миграции 0015 (обязательные «Марка кабеля»/«Длина», список состояний
 *    кабеля, единицы мм²/кВ);
 *  - набор типов и классы — рабочая `karier_db` (PS-35/БКРУ → Распредустройства,
 *    КТП/КСР/ЯКУ-1т → Трансформаторы и сборки, ЯКНО/ЯКУ → Коммутационные,
 *    ячейки → Ячейки, генераторы/ДМО → Мобильное, опора → Опоры).
 */

import { describe, expect, it } from 'vitest'
import { ApiError } from './api'
import type { AssetType, AssetTypeField } from './gis'
import {
  EQUIPMENT_GROUPS,
  buildAttrs,
  cableLifecycleStatus,
  defaultAttrValues,
  groupFields,
  groupOfType,
  groupTypes,
  mapServerFieldErrors,
  missingRequiredLabels,
  optionLabel,
  typeFields,
  typesOfGroup,
  validateAssetFields,
} from './assetFields'

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

/** Ответ `GET /api/asset-types?with_fields=1` для типа `cable` (karier_test_db). */
const CABLE_FIELDS: AssetTypeField[] = [
  {
    id: 'f-1',
    code: 'cable_mark',
    label: 'Марка кабеля',
    unit: null,
    data_type: 'text',
    required: true,
    default_value: null,
    options: [],
    group_label: 'Кабель',
    sort_order: 10,
  },
  {
    id: 'f-2',
    code: 'length_m',
    label: 'Длина',
    unit: 'м',
    data_type: 'number',
    required: true,
    default_value: null,
    options: [],
    group_label: 'Кабель',
    sort_order: 20,
  },
  {
    id: 'f-3',
    code: 'lifecycle_status',
    label: 'Состояние кабеля',
    unit: null,
    data_type: 'select',
    required: false,
    default_value: 'installed',
    options: ['installed', 'reserve', 'repair'],
    group_label: 'Кабель',
    sort_order: 30,
  },
  {
    id: 'f-4',
    code: 'section_mm2',
    label: 'Сечение',
    unit: 'мм²',
    data_type: 'number',
    required: false,
    default_value: null,
    options: [],
    group_label: 'Кабель',
    sort_order: 40,
  },
  {
    id: 'f-5',
    code: 'voltage_kv',
    label: 'Напряжение',
    unit: 'кВ',
    data_type: 'number',
    required: false,
    default_value: null,
    options: [],
    group_label: 'Напряжение',
    sort_order: 50,
  },
]

const CABLE = makeType({
  code: 'cable',
  name: 'Кабель',
  category: 'line',
  equipment_class: 'cable',
  group_code: 'cables',
  attr_schema: {
    cable_mark: { type: 'string' },
    length_m: { type: 'number' },
  },
  required_attrs: ['cable_mark', 'length_m'],
  fields: CABLE_FIELDS,
})

/** Типы рабочей БД: классы/вкладки из миграции 0015. */
const PROD_TYPES: AssetType[] = [
  makeType({
    code: 'ps_35',
    name: 'ПС 35-6 кВ Карьер',
    equipment_class: 'distribution',
    group_code: 'distribution',
  }),
  makeType({ code: 'bkru_1', name: 'БКРУ-1', equipment_class: 'distribution', group_code: 'distribution' }),
  makeType({ code: 'ktp', name: 'КТП', equipment_class: 'transformer_assembly', group_code: 'transformers' }),
  makeType({
    code: 'yaku_1t',
    name: 'Яку-1т',
    equipment_class: 'transformer_assembly',
    group_code: 'transformers',
  }),
  makeType({ code: 'yaku', name: 'Яку воздух-кабель', equipment_class: 'switching', group_code: 'switching' }),
  makeType({ code: 'yacheyka_3', name: 'Ячейка ПС 35-6', equipment_class: 'cell', group_code: 'cells' }),
  makeType({ code: 'cable', name: 'Кабель', equipment_class: 'cable', group_code: 'cables' }),
  makeType({
    code: 'generator_dizelnyy',
    name: 'Генератор Дизельный',
    equipment_class: 'mobile',
    group_code: 'mobile',
  }),
  makeType({ code: 'op', name: 'Опора', equipment_class: 'line', group_code: 'lines' }),
  makeType({ code: 'source_35', name: 'Питающий центр', equipment_class: 'source', group_code: 'sources' }),
]

describe('группы классов оборудования', () => {
  it('показывает утверждённые русские вкладки в нужном порядке', () => {
    expect(EQUIPMENT_GROUPS.map((group) => group.title)).toEqual([
      'Распредустройства',
      'Трансформаторы и сборки',
      'Коммутационные',
      'Ячейки',
      'Кабели',
      'Мобильное',
      'Опоры',
      'Источники',
    ])
  })

  it('раскладывает типы рабочей БД по вкладкам и не показывает пустые', () => {
    const groups = groupTypes(PROD_TYPES)
    expect(groups.map((item) => item.group.title)).toEqual([
      'Распредустройства',
      'Трансформаторы и сборки',
      'Коммутационные',
      'Ячейки',
      'Кабели',
      'Мобильное',
      'Опоры',
      'Источники',
    ])
    expect(typesOfGroup(groups, 'distribution').map((type) => type.code)).toEqual(['ps_35', 'bkru_1'])
    expect(typesOfGroup(groups, 'transformer_assembly').map((type) => type.code)).toEqual([
      'ktp',
      'yaku_1t',
    ])
    expect(typesOfGroup(groups, 'cell').map((type) => type.code)).toEqual(['yacheyka_3'])
  })

  it('скрывает вкладки без типов', () => {
    const groups = groupTypes(PROD_TYPES.filter((type) => type.equipment_class !== 'mobile'))
    expect(groups.map((item) => item.group.code)).not.toContain('mobile')
    expect(typesOfGroup(groups, 'mobile')).toEqual([])
  })

  it('определяет вкладку по group_code и категории, если класса нет (старый API)', () => {
    const byGroupCode = makeType({ code: 'x', name: 'X', group_code: 'transformers' })
    expect(groupOfType(byGroupCode).title).toBe('Трансформаторы и сборки')

    const lineByCategory = makeType({ code: 'pole', name: 'Опора', category: 'pole' })
    expect(groupOfType(lineByCategory).title).toBe('Опоры')

    const fallback = makeType({ code: 'unknown', name: 'Нечто', category: 'equipment' })
    expect(groupOfType(fallback).title).toBe('Прочее')
  })
})

describe('поля паспорта типа', () => {
  it('отдаёт поля типа из asset_type_fields с подписями, единицами и обязательностью', () => {
    const fields = typeFields(CABLE)
    expect(fields.map((field) => field.code)).toEqual([
      'cable_mark',
      'length_m',
      'lifecycle_status',
      'section_mm2',
      'voltage_kv',
    ])
    const mark = fields.find((field) => field.code === 'cable_mark')!
    expect(mark.label).toBe('Марка кабеля')
    expect(mark.required).toBe(true)
    expect(mark.data_type).toBe('text')

    const length = fields.find((field) => field.code === 'length_m')!
    expect(length.unit).toBe('м')
    expect(length.data_type).toBe('number')
    expect(length.required).toBe(true)

    const status = fields.find((field) => field.code === 'lifecycle_status')!
    expect(status.data_type).toBe('select')
    expect(status.options).toEqual(['installed', 'reserve', 'repair'])
    expect(status.default_value).toBe('installed')
  })

  it('выводит поля из attr_schema, если API не отдал fields (старый backend)', () => {
    const legacy = makeType({
      code: 'ktp',
      name: 'КТП',
      attr_schema: {
        voltage_out_kv: { type: 'number' },
        power_kw: { type: 'number' },
        serial_no: { type: 'string', label: 'Серийный номер' },
      },
      required_attrs: ['serial_no'],
    })
    const fields = typeFields(legacy)
    // обязательные — первыми, дальше по алфавиту (как в миграторе 0015)
    expect(fields.map((field) => field.code)).toEqual(['serial_no', 'power_kw', 'voltage_out_kv'])
    expect(fields[0].label).toBe('Серийный номер')
    expect(fields[0].required).toBe(true)
    expect(fields[1].label).toBe('Мощность')
    expect(fields[1].unit).toBe('кВт')
    expect(fields[2].data_type).toBe('number')
    // legacy `string` → text
    expect(fields[0].data_type).toBe('text')
  })

  it('поддерживает все типы данных формы: число, целое, текст, да/нет, дата, список', () => {
    const type = makeType({
      code: 'mixed',
      name: 'Смешанный',
      fields: [
        { code: 'a', label: 'Число', data_type: 'number' },
        { code: 'b', label: 'Целое', data_type: 'integer' },
        { code: 'c', label: 'Текст', data_type: 'text' },
        { code: 'd', label: 'Да/нет', data_type: 'boolean' },
        { code: 'e', label: 'Дата', data_type: 'date' },
        { code: 'f', label: 'Список', data_type: 'select', options: ['да', 'нет'] },
      ],
    })
    expect(typeFields(type).map((field) => field.data_type)).toEqual([
      'number',
      'integer',
      'text',
      'boolean',
      'date',
      'select',
    ])
  })

  it('группирует поля по group_label', () => {
    const sections = groupFields(typeFields(CABLE))
    expect(sections.map((section) => section.label)).toEqual(['Кабель', 'Напряжение'])
    expect(sections[0].fields).toHaveLength(4)
    expect(sections[1].fields[0].code).toBe('voltage_kv')
  })

  it('берёт стартовые значения из default_value', () => {
    expect(defaultAttrValues(typeFields(CABLE))).toEqual({ lifecycle_status: 'installed' })
    const withBoolean = makeType({
      code: 'b',
      name: 'B',
      fields: [
        { code: 'section_breaker', label: 'Секционный', data_type: 'boolean', default_value: false },
        { code: 'power_kw', label: 'Мощность', data_type: 'number', default_value: 100 },
      ],
    })
    expect(defaultAttrValues(typeFields(withBoolean))).toEqual({
      section_breaker: 'false',
      power_kw: '100',
    })
  })

  it('переводит значения списка на русский, если перевод известен', () => {
    expect(optionLabel('lifecycle_status', 'reserve')).toBe('в запасе')
    expect(optionLabel('other', 'reserve')).toBe('reserve')
  })
})

describe('клиентская проверка обязательных полей и типов', () => {
  const fields = typeFields(CABLE)

  it('требует заполнить обязательные поля до отправки', () => {
    const errors = validateAssetFields(fields, {})
    expect(errors).toEqual({
      cable_mark: 'Обязательное поле',
      length_m: 'Обязательное поле',
    })
    expect(missingRequiredLabels(fields, {})).toEqual(['Марка кабеля', 'Длина'])
  })

  it('не пропускает нечисловое значение в числовое поле', () => {
    const errors = validateAssetFields(fields, { cable_mark: 'ВВГ', length_m: 'много' })
    expect(errors).toEqual({ length_m: 'Ожидается число' })
  })

  it('принимает число с запятой и точкой', () => {
    expect(validateAssetFields(fields, { cable_mark: 'ВВГ', length_m: '1250,5' })).toEqual({})
    expect(validateAssetFields(fields, { cable_mark: 'ВВГ', length_m: '1250.5' })).toEqual({})
  })

  it('проверяет целые, да/нет, даты и min/max', () => {
    const typed = makeType({
      code: 'typed',
      name: 'Typed',
      fields: [
        { code: 'count', label: 'Количество', data_type: 'integer' },
        { code: 'flag', label: 'Флаг', data_type: 'boolean' },
        { code: 'on', label: 'Дата', data_type: 'date' },
        { code: 'power', label: 'Мощность', data_type: 'number', min: 1, max: 100 },
      ],
    })
    const typedFields = typeFields(typed)
    expect(validateAssetFields(typedFields, { count: '1,5' })).toEqual({
      count: 'Ожидается целое число',
    })
    expect(validateAssetFields(typedFields, { count: '2' })).toEqual({})
    expect(validateAssetFields(typedFields, { flag: 'да' })).toEqual({ flag: 'Ожидается да/нет' })
    expect(validateAssetFields(typedFields, { flag: 'true' })).toEqual({})
    expect(validateAssetFields(typedFields, { on: '26.11.2026' })).toEqual({
      on: 'Ожидается дата в формате ГГГГ-ММ-ДД',
    })
    expect(validateAssetFields(typedFields, { on: '2026-11-26' })).toEqual({})
    expect(validateAssetFields(typedFields, { power: '0' })).toEqual({
      power: 'Значение меньше минимального (1)',
    })
    expect(validateAssetFields(typedFields, { power: '101' })).toEqual({
      power: 'Значение больше максимального (100)',
    })
  })

  it('не пропускает значение, которого нет в списке', () => {
    const errors = validateAssetFields(typeFields(CABLE), {
      cable_mark: 'ВВГ',
      length_m: '10',
      lifecycle_status: 'bogus',
    })
    expect(errors.lifecycle_status).toBe('Недопустимое значение (допустимо: installed, reserve, repair)')
  })

  it('собирает attrs: числа числами, да/нет булевым, пустые не отправляются', () => {
    const attrs = buildAttrs(fields, {
      cable_mark: 'ВВГ 3×2,5',
      length_m: '305,5',
      section_mm2: '2.5',
      lifecycle_status: 'reserve',
      voltage_kv: '',
    })
    expect(attrs).toEqual({
      cable_mark: 'ВВГ 3×2,5',
      length_m: 305.5,
      section_mm2: 2.5,
      lifecycle_status: 'reserve',
    })
  })

  it('собирает attrs для целых и да/нет', () => {
    const typed = makeType({
      code: 'typed2',
      name: 'Typed2',
      fields: [
        { code: 'cell_no', label: 'Номер ячейки', data_type: 'integer' },
        { code: 'section_breaker', label: 'Секционный', data_type: 'boolean' },
      ],
    })
    expect(buildAttrs(typeFields(typed), { cell_no: '3', section_breaker: 'true' })).toEqual({
      cell_no: 3,
      section_breaker: true,
    })
  })

  it('состояние кабеля уходит и в attrs, и в отдельную колонку lifecycle_status', () => {
    expect(cableLifecycleStatus(fields, { lifecycle_status: 'reserve' })).toBe('reserve')
    expect(cableLifecycleStatus(fields, { lifecycle_status: 'installed' })).toBe('installed')
    expect(cableLifecycleStatus(fields, { lifecycle_status: 'bogus' })).toBeNull()
    expect(cableLifecycleStatus(fields, {})).toBeNull()
    // у типа без такого поля колонку не трогаем
    expect(cableLifecycleStatus(typeFields(PROD_TYPES[2]), { lifecycle_status: 'reserve' })).toBeNull()
  })
})

describe('серверные 422: fields + field_labels под полями формы', () => {
  const fields = typeFields(CABLE)

  it('раскладывает реальный ответ 422 по полям паспорта с русскими подписями', () => {
    const mapped = mapServerFieldErrors(
      fields,
      { cable_mark: 'Обязательное поле', length_m: 'Обязательное поле' },
      { cable_mark: 'Марка кабеля', length_m: 'Длина' },
    )
    expect(mapped.attrs).toEqual({
      cable_mark: 'Обязательное поле',
      length_m: 'Обязательное поле',
    })
    expect(mapped.labels).toEqual({ cable_mark: 'Марка кабеля', length_m: 'Длина' })
    expect(mapped.base).toEqual({})
    expect(mapped.unmatched).toEqual([])
    // Сводка объясняет, что именно проверить — без «Проверьте атрибуты объекта»
    expect(mapped.summary).toContain('поля паспорта')
    expect(mapped.summary).toContain('Марка кабеля')
    expect(mapped.summary).not.toContain('атрибуты объекта')
  })

  it('понимает путь attrs.<code> и подписи без field_labels (берёт из типа)', () => {
    const mapped = mapServerFieldErrors(fields, { 'attrs.length_m': 'Ожидается число' })
    expect(mapped.attrs).toEqual({ length_m: 'Ожидается число' })
    expect(mapped.labels.length_m).toBe('Длина')
    expect(mapped.summary).toContain('Длина')
  })

  it('отделяет ошибки основных полей формы (название, тип, координаты)', () => {
    const mapped = mapServerFieldErrors(
      fields,
      { name: 'обязательное поле', type_code: 'недопустимый тип', x: 'ожидается число' },
      { name: 'Название', type_code: 'Тип', x: 'X' },
    )
    expect(mapped.base).toEqual({
      name: 'обязательное поле',
      type_code: 'недопустимый тип',
      x: 'ожидается число',
    })
    expect(mapped.attrs).toEqual({})
    expect(mapped.summary).toContain('основные поля')
    expect(mapped.summary).toContain('Название')
  })

  it('не теряет незнакомый ключ: показывает его в сводке, а не молча пропускает', () => {
    const mapped = mapServerFieldErrors(fields, { warranty_until: 'Ожидается дата' })
    expect(mapped.attrs).toEqual({})
    expect(mapped.base).toEqual({})
    expect(mapped.unmatched).toEqual(['Warranty until: Ожидается дата'])
    expect(mapped.summary).toContain('Warranty until: Ожидается дата')
  })

  it('ApiError сохраняет field_labels рядом с машинными fields', () => {
    const error = new ApiError(422, {
      code: 'validation.failed',
      detail: 'Проверьте поля объекта: Марка кабеля, Длина',
      fields: { cable_mark: 'Обязательное поле' },
      field_labels: { cable_mark: 'Марка кабеля' },
    })
    expect(error.status).toBe(422)
    expect(error.fields).toEqual({ cable_mark: 'Обязательное поле' })
    expect(error.fieldLabels).toEqual({ cable_mark: 'Марка кабеля' })
    const mapped = mapServerFieldErrors(fields, error.fields, error.fieldLabels)
    expect(mapped.attrs.cable_mark).toBe('Обязательное поле')
    expect(mapped.labels.cable_mark).toBe('Марка кабеля')
  })
})
