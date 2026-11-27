/**
 * Рендер динамической формы создания объекта (без DOM: `renderToStaticMarkup`).
 * Проверяем то, что видит админ: вкладки классов, подписи/единицы полей,
 * пометку обязательных, input под каждый `data_type` и ошибку под полем.
 */

import { describe, expect, it } from 'vitest'
import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { DynamicAssetFields, TypeGroupTabs } from './DynamicFields'
import type { AssetType, AssetTypeField } from '../../lib/gis'
import { groupTypes, typeFields } from '../../lib/assetFields'

function markup(node: ReactElement): string {
  return renderToStaticMarkup(node)
}

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

const CABLE = makeType({
  code: 'cable',
  name: 'Кабель',
  equipment_class: 'cable',
  group_code: 'cables',
  fields: [
    { code: 'cable_mark', label: 'Марка кабеля', data_type: 'text', required: true },
    { code: 'length_m', label: 'Длина', unit: 'м', data_type: 'number', required: true },
    {
      code: 'lifecycle_status',
      label: 'Состояние кабеля',
      data_type: 'select',
      options: ['installed', 'reserve', 'repair'],
      default_value: 'installed',
    },
  ],
})

const ALL_TYPES = makeType({
  code: 'mixed',
  name: 'Смешанный',
  fields: [
    { code: 'power_kw', label: 'Мощность', unit: 'кВт', data_type: 'number' },
    { code: 'cell_no', label: 'Номер ячейки', data_type: 'integer' },
    { code: 'serial_no', label: 'Заводской номер', data_type: 'text' },
    { code: 'section_breaker', label: 'Секционный выключатель', data_type: 'boolean' },
    { code: 'commissioned_on', label: 'Дата ввода', data_type: 'date' },
    { code: 'drive_type', label: 'Тип привода', data_type: 'text', group_label: 'Исполнение' },
  ] satisfies AssetTypeField[],
})

describe('тип-селект по классам', () => {
  it('рисует вкладки классов с русскими названиями и выбранным классом', () => {
    const groups = groupTypes([
      makeType({ code: 'ktp', name: 'КТП', equipment_class: 'transformer_assembly' }),
      makeType({ code: 'cable', name: 'Кабель', equipment_class: 'cable' }),
    ])
    const html = markup(<TypeGroupTabs groups={groups} value="cable" onChange={() => undefined} />)
    expect(html).toContain('Трансформаторы и сборки')
    expect(html).toContain('Кабели')
    expect(html).toMatch(/aria-pressed="true"[^>]*>[^<]*<span[^>]*>🧵/)
    expect(html).toContain('data-testid="equipment-class-cables"')
  })
})

describe('поля паспорта в форме', () => {
  it('показывает подписи, единицы и пометку обязательных полей', () => {
    const fields = typeFields(CABLE)
    const html = markup(
      <DynamicAssetFields
        fields={fields}
        values={{ lifecycle_status: 'installed' }}
        errors={{}}
        onChange={() => undefined}
      />,
    )
    expect(html).toContain('Марка кабеля')
    expect(html).toContain('Длина')
    expect(html).toContain(', м')
    expect(html).toContain('Состояние кабеля')
    // обязательные помечены звёздочкой и aria-required
    expect(html).toContain('aria-required="true"')
    expect(html).toContain('title="Обязательное поле"')
    // список состояний кабеля — по-русски
    expect(html).toContain('на оборудовании')
    expect(html).toContain('в запасе')
    expect(html).toContain('в ремонте')
    expect(html).toContain('value="installed" selected=""')
  })

  it('рисует input под каждый data_type', () => {
    const html = markup(
      <DynamicAssetFields
        fields={typeFields(ALL_TYPES)}
        values={{}}
        errors={{}}
        onChange={() => undefined}
      />,
    )
    expect(html).toMatch(/inputmode="decimal"/i)
    expect(html).toMatch(/inputmode="numeric"/i)
    expect(html).toContain('type="date"')
    expect(html).toContain('кВт')
    expect(html).toContain('Исполнение')
    // boolean — select «да/нет»
    expect(html).toMatch(/<select[^>]*>.*— не задано —.*да.*нет.*<\/select>/s)
  })

  it('выводит серверную ошибку под соответствующим полем', () => {
    const fields = typeFields(CABLE)
    const html = markup(
      <DynamicAssetFields
        fields={fields}
        values={{}}
        errors={{ cable_mark: 'Обязательное поле', length_m: 'Ожидается число' }}
        onChange={() => undefined}
      />,
    )
    expect(html).toContain('aria-invalid="true"')
    expect(html).toContain('aria-describedby="asset-attr-cable_mark-error"')
    expect(html).toContain('asset-attr-cable_mark-error')
    expect(html).toContain('role="alert"')
    expect(html).toContain('Обязательное поле')
    expect(html).toContain('Ожидается число')
  })

  it('не пугает админа пустой формой: у типа без полей есть подсказка', () => {
    const html = markup(
      <DynamicAssetFields fields={[]} values={{}} errors={{}} onChange={() => undefined} />,
    )
    expect(html).toContain('нет полей паспорта')
  })
})
