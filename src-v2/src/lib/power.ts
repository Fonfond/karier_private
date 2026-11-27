/**
 * Электробезопасность на UI: цвет и текст состояния «под напряжением».
 *
 * Требование заказчика (этап 2 модели оборудования): включено / под напряжением —
 * КРАСНЫЙ (`#F04438`), отключено / обесточено / заземлено — ЗЕЛЁНЫЙ (`#22C55E`).
 * Один и тот же цвет применяется на схеме, в карточке объекта, в списках и в
 * легенде, а рядом всегда есть текст (и иконка) — состояние понятно и без цвета
 * (доступность, скринридеры, дальтоники).
 *
 * Модуль чистый (без React): его проверяют unit-тесты `power.test.ts`.
 */

import { POWER_COLOR, STATUS_COLOR, STATUS_LABEL } from './gis'

/** Текстовые подписи питания — единый словарь для всех экранов. */
export const POWER_TEXT = {
  on: 'под напряжением',
  off: 'обесточено',
  grounded: 'заземлено',
} as const

export interface PowerState {
  /** Оперативно «под напряжением»: включено и не заземлено. */
  energized: boolean
  /** Цвет по электробезопасности: красный — под напряжением, зелёный — обесточено. */
  color: string
  /** Короткая подпись для бейджа/строки списка. */
  label: string
  /** Полная подпись для title/aria-label (состояние + пояснение). */
  title: string
  /** Иконка-дубль цвета (⚡ / ○ / ⏚): состояние читается без цвета. */
  icon: string
  /** Машинный вид: on | off | grounded | standby | maintenance | decommissioned… */
  kind: string
}

/** Включено и не заземлено — объект под напряжением. */
export function isEnergized(status: string | null | undefined, grounded?: boolean | null): boolean {
  return Boolean(!grounded && status === 'on')
}

/**
 * Состояние по электробезопасности для статуса `gis.assets.status`.
 * Заземление важнее статуса: заземлённый объект всегда обесточен и зелёный.
 */
export function powerStateOf(status: string | null | undefined, grounded?: boolean | null): PowerState {
  const value = (status ?? '').trim().toLowerCase()

  if (grounded) {
    return {
      energized: false,
      color: POWER_COLOR.off,
      label: POWER_TEXT.grounded,
      title: 'Заземлено — объект обесточен',
      icon: '⏚',
      kind: 'grounded',
    }
  }

  if (value === 'on') {
    return {
      energized: true,
      color: POWER_COLOR.on,
      label: POWER_TEXT.on,
      title: 'Включено — объект под напряжением',
      icon: '⚡',
      kind: 'on',
    }
  }

  if (value === 'off' || value === '') {
    return {
      energized: false,
      color: POWER_COLOR.off,
      label: POWER_TEXT.off,
      title: 'Отключено — объект обесточен',
      icon: '○',
      kind: 'off',
    }
  }

  if (value === 'standby') {
    return {
      energized: false,
      color: POWER_COLOR.off,
      label: 'резерв · обесточено',
      title: 'В резерве — объект обесточен',
      icon: '○',
      kind: 'standby',
    }
  }

  // Ремонт/списание — не про напряжение: оставляем эксплуатационный цвет,
  // но и здесь подпись важнее цвета.
  return {
    energized: false,
    color: STATUS_COLOR[value] ?? '#6B7A8A',
    label: STATUS_LABEL[value] ?? value,
    title: `Состояние: ${STATUS_LABEL[value] ?? value}`,
    icon: '●',
    kind: value || 'unknown',
  }
}

/** Подпись напряжения: «6 кВ» при включении, «0 кВ» — при обесточивании. */
export function voltageText(energized: boolean, voltageKv?: number | null): string {
  const nominal = voltageKv != null && Number.isFinite(voltageKv) ? voltageKv : null
  if (!energized) return '0 кВ'
  if (nominal == null) return 'напряжение есть'
  return `${formatKv(nominal)} кВ`
}

/** Число киловольт без хвоста `.0` (6, 35, 0.4). */
export function formatKv(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100)
}

/** Готовая строка состояния для aria-label кнопки переключения. */
export function toggleAriaLabel(action: 'on' | 'off', name: string, power: PowerState): string {
  if (action === 'on') return `Включить «${name}» (сейчас ${power.label})`
  return `Отключить «${name}» (сейчас ${power.label})`
}

/**
 * Минимальный набор полей, который приходит из карточки после переключения
 * (ячейка/разъединитель/ребёнок блока): `AssetOut` и `ChildAsset` его содержат.
 */
export interface PowerStateUpdate {
  id: string
  status: string
  grounded: boolean
}

/**
 * Обновить локальный список объектов после toggle из карточки.
 *
 * Нужен, чтобы схема перекрасилась сразу, без перезагрузки страницы: MapPage
 * держит `assets` (реестр) и отдаёт из него `assetStates` в `SchemaView`.
 * Возвращает тот же массив, если ничего не изменилось, — лишних перерисовок нет.
 */
export function applyPowerState<T extends { id: string; status: string; grounded: boolean }>(
  items: T[],
  update: PowerStateUpdate,
): T[] {
  let changed = false
  const next = items.map((item) => {
    if (item.id !== update.id) return item
    if (item.status === update.status && item.grounded === update.grounded) return item
    changed = true
    return { ...item, status: update.status, grounded: update.grounded }
  })
  return changed ? next : items
}

/** Сводка по группе состояний — для шапки блока ПС/БКРУ на схеме. */
export function powerSummary(states: Array<{ status: string; grounded?: boolean | null }>): {
  energized: number
  off: number
  total: number
  text: string
} {
  let energized = 0
  for (const item of states) if (isEnergized(item.status, item.grounded)) energized += 1
  const total = states.length
  return {
    energized,
    off: total - energized,
    total,
    text: `${energized} под напряжением · ${total - energized} обесточено`,
  }
}
