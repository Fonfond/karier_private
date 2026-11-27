/**
 * Элементы динамической формы создания объекта (этап 1 модели «Карьер»).
 *
 * `TypeGroupTabs` — вкладки классов оборудования вместо плоского списка типов;
 * `DynamicAssetFields` — поля паспорта выбранного типа: подпись, единица,
 * обязательность и input по `data_type` (`number`, `integer`, `text`, `boolean`,
 * `date`, `select`). Ошибка рисуется под своим полем (`aria-invalid`).
 */

import type { ChangeEvent, ReactNode } from 'react'
import type { AssetTypeField } from '../../lib/gis'
import type { AttrValues, FieldErrors, TypeGroup } from '../../lib/assetFields'
import { groupFields, optionLabel } from '../../lib/assetFields'

export function TypeGroupTabs({
  groups,
  value,
  onChange,
}: {
  groups: TypeGroup[]
  value: string
  onChange: (code: string) => void
}) {
  if (groups.length === 0) return null
  return (
    <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1" role="group" aria-label="Класс оборудования">
      {groups.map(({ group, types }) => {
        const active = group.code === value
        return (
          <button
            key={group.code}
            type="button"
            aria-pressed={active}
            data-testid={`equipment-class-${group.groupCode}`}
            className={`h-9 shrink-0 rounded-full border px-3 text-[12px] transition ${
              active
                ? 'border-accent bg-accent/15 text-accent'
                : 'border-line text-ink2 hover:bg-surface2'
            }`}
            onClick={() => onChange(group.code)}
          >
            <span className="mr-1" aria-hidden="true">
              {group.icon}
            </span>
            {group.title}
            <span className="ml-1.5 text-[11px] text-ink3">{types.length}</span>
          </button>
        )
      })}
    </div>
  )
}

function ErrorLine({ id, message }: { id: string; message: string }) {
  return (
    <span id={id} role="alert" className="mt-1 block text-[12px] text-danger">
      {message}
    </span>
  )
}

function Control({
  field,
  value,
  invalid,
  describedBy,
  disabled,
  onChange,
}: {
  field: AssetTypeField
  value: string
  invalid: boolean
  describedBy?: string
  disabled: boolean
  onChange: (value: string) => void
}) {
  const inputId = `asset-attr-${field.code}`
  const common = {
    id: inputId,
    className: 'input',
    value,
    disabled,
    'aria-required': field.required ? true : undefined,
    'aria-invalid': invalid || undefined,
    'aria-describedby': describedBy,
    onChange: (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      onChange(event.target.value),
  }

  if (field.data_type === 'boolean') {
    return (
      <select {...common}>
        <option value="">— не задано —</option>
        <option value="true">да</option>
        <option value="false">нет</option>
      </select>
    )
  }

  if (field.data_type === 'select') {
    const options = field.options ?? []
    // Нет списка опций — backend допускает любое значение, поэтому text-инпут.
    if (options.length === 0) {
      return (
        <input
          {...common}
          type="text"
          placeholder="значение"
          autoComplete="off"
        />
      )
    }
    return (
      <select {...common}>
        <option value="">— выберите —</option>
        {options.map((option) => (
          <option key={String(option)} value={String(option)}>
            {optionLabel(field.code, option)}
          </option>
        ))}
      </select>
    )
  }

  if (field.data_type === 'date') {
    return <input {...common} type="date" />
  }

  if (field.data_type === 'number' || field.data_type === 'integer') {
    const placeholder =
      field.data_type === 'integer'
        ? 'целое число'
        : field.unit
          ? `например 250 ${field.unit}`
          : 'например 250,5'
    return (
      <div className="relative">
        <input
          {...common}
          type="text"
          inputMode={field.data_type === 'integer' ? 'numeric' : 'decimal'}
          placeholder={placeholder}
          autoComplete="off"
          className={`${common.className} ${field.unit ? 'pr-14' : ''}`}
        />
        {field.unit ? (
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[12px] text-ink3">
            {field.unit}
          </span>
        ) : null}
      </div>
    )
  }

  return <input {...common} type="text" placeholder="значение" autoComplete="off" />
}

export function DynamicFieldInput({
  field,
  value,
  error,
  disabled = false,
  onChange,
}: {
  field: AssetTypeField
  value: string
  error?: string
  disabled?: boolean
  onChange: (value: string) => void
}) {
  const errorId = `asset-attr-${field.code}-error`
  const control: ReactNode = (
    <Control
      field={field}
      value={value}
      invalid={Boolean(error)}
      describedBy={error ? errorId : undefined}
      disabled={disabled}
      onChange={onChange}
    />
  )
  return (
    <label className="block" htmlFor={`asset-attr-${field.code}`} data-testid={`asset-field-${field.code}`}>
      <span className="label">
        {field.label}
        {field.required ? (
          <span className="ml-0.5 text-danger" title="Обязательное поле" aria-label="обязательное">
            *
          </span>
        ) : null}
        {field.unit ? <span className="ml-1 font-normal text-ink3">, {field.unit}</span> : null}
      </span>
      {control}
      {error ? <ErrorLine id={errorId} message={error} /> : null}
    </label>
  )
}

export function DynamicAssetFields({
  fields,
  values,
  errors,
  disabled = false,
  emptyHint = 'У этого типа нет полей паспорта: админ задаёт их в разделе «Типы объектов».',
  onChange,
}: {
  fields: AssetTypeField[]
  values: AttrValues
  errors: FieldErrors
  disabled?: boolean
  emptyHint?: string
  onChange: (code: string, value: string) => void
}) {
  if (fields.length === 0) {
    return <p className="text-[12px] text-ink3">{emptyHint}</p>
  }
  const sections = groupFields(fields)
  return (
    <div className="space-y-3">
      <p className="text-[11px] text-ink3">
        Поля паспорта из типа оборудования: <span className="text-danger">*</span> — обязательное,
        единица указана рядом с названием.
      </p>
      {sections.map((section) => (
        <fieldset key={section.label} className="space-y-2">
          <legend className="label">{section.label}</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {section.fields.map((field) => (
              <DynamicFieldInput
                key={field.code}
                field={field}
                value={values[field.code] ?? ''}
                error={errors[field.code]}
                disabled={disabled}
                onChange={(value) => onChange(field.code, value)}
              />
            ))}
          </div>
        </fieldset>
      ))}
    </div>
  )
}
