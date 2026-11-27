/**
 * Тесты электробезопасности UI (этап 2 модели оборудования).
 *
 * Требование заказчика: включено / под напряжением — красный `#F04438`,
 * отключено / обесточено / заземлено — зелёный `#22C55E`; цвет всегда
 * продублирован текстом и иконкой (доступность).
 */

import { describe, expect, it } from 'vitest'
import { POWER_COLOR } from './gis'
import {
  POWER_TEXT,
  applyPowerState,
  formatKv,
  isEnergized,
  powerStateOf,
  powerSummary,
  toggleAriaLabel,
  voltageText,
} from './power'

describe('powerStateOf: цвета по электробезопасности', () => {
  it('включено — красный и текст «под напряжением»', () => {
    const state = powerStateOf('on', false)
    expect(state.energized).toBe(true)
    expect(state.color).toBe('#F04438')
    expect(state.color).toBe(POWER_COLOR.on)
    expect(state.label).toBe(POWER_TEXT.on)
    expect(state.icon).toBe('⚡')
    expect(state.title).toContain('под напряжением')
  })

  it('отключено — зелёный и текст «обесточено»', () => {
    const state = powerStateOf('off', false)
    expect(state.energized).toBe(false)
    expect(state.color).toBe('#22C55E')
    expect(state.color).toBe(POWER_COLOR.off)
    expect(state.label).toBe(POWER_TEXT.off)
    expect(state.icon).toBe('○')
  })

  it('заземлено — зелёный даже если статус «on»', () => {
    const state = powerStateOf('on', true)
    expect(state.energized).toBe(false)
    expect(state.color).toBe('#22C55E')
    expect(state.label).toBe(POWER_TEXT.grounded)
    expect(state.icon).toBe('⏚')
  })

  it('резерв — зелёный с уточнением «обесточено»', () => {
    const state = powerStateOf('standby', false)
    expect(state.energized).toBe(false)
    expect(state.color).toBe('#22C55E')
    expect(state.label).toContain('обесточено')
  })

  it('ремонт и списание не выдаются за напряжение', () => {
    expect(powerStateOf('maintenance', false).energized).toBe(false)
    expect(powerStateOf('decommissioned', false).energized).toBe(false)
  })

  it('состояние всегда содержит текст, а не только цвет', () => {
    for (const status of ['on', 'off', 'standby', 'maintenance']) {
      const state = powerStateOf(status, false)
      expect(state.label.trim().length).toBeGreaterThan(0)
      expect(state.icon.length).toBeGreaterThan(0)
      expect(state.title.length).toBeGreaterThan(0)
    }
  })
})

describe('isEnergized', () => {
  it('только on без заземления', () => {
    expect(isEnergized('on', false)).toBe(true)
    expect(isEnergized('on', null)).toBe(true)
    expect(isEnergized('on', true)).toBe(false)
    expect(isEnergized('off', false)).toBe(false)
    expect(isEnergized(null, false)).toBe(false)
    expect(isEnergized(undefined, undefined)).toBe(false)
  })
})

describe('подписи напряжения и кнопок', () => {
  it('при включении показывает номинал, при отключении — 0 кВ', () => {
    expect(voltageText(true, 6)).toBe('6 кВ')
    expect(voltageText(true, 35)).toBe('35 кВ')
    expect(voltageText(true, 0.4)).toBe('0.4 кВ')
    expect(voltageText(true, null)).toBe('напряжение есть')
    expect(voltageText(false, 6)).toBe('0 кВ')
  })

  it('formatKv убирает хвост .0', () => {
    expect(formatKv(6)).toBe('6')
    expect(formatKv(6.0)).toBe('6')
    expect(formatKv(0.4)).toBe('0.4')
    expect(formatKv(6.25)).toBe('6.25')
  })

  it('aria-label кнопки содержит действие, имя и текущее состояние', () => {
    expect(toggleAriaLabel('on', 'Яч. №3', powerStateOf('off', false))).toBe(
      'Включить «Яч. №3» (сейчас обесточено)',
    )
    expect(toggleAriaLabel('off', 'Вводной разъединитель', powerStateOf('on', false))).toBe(
      'Отключить «Вводной разъединитель» (сейчас под напряжением)',
    )
  })
})

describe('powerSummary для шапки блока ПС/БКРУ', () => {
  it('считает включённые и обесточенные ячейки', () => {
    const summary = powerSummary([
      { status: 'on', grounded: false },
      { status: 'off', grounded: false },
      { status: 'on', grounded: true },
    ])
    expect(summary.energized).toBe(1)
    expect(summary.off).toBe(2)
    expect(summary.total).toBe(3)
    expect(summary.text).toBe('1 под напряжением · 2 обесточено')
  })
})

describe('applyPowerState: обновление локального списка после toggle из карточки', () => {
  const items = [
    { id: 'cell-1', code: 'CELL-1', status: 'off', grounded: false, name: 'Яч. №1' },
    { id: 'cell-2', code: 'CELL-2', status: 'on', grounded: false, name: 'Яч. №2' },
  ]

  it('меняет статус только выбранного объекта, остальные не трогает', () => {
    const next = applyPowerState(items, { id: 'cell-1', status: 'on', grounded: false })
    expect(next).not.toBe(items)
    expect(next[0].status).toBe('on')
    expect(next[1]).toBe(items[1])
    expect(next.map((item) => item.code)).toEqual(['CELL-1', 'CELL-2'])
  })

  it('обновляет заземление: включено + заземлено = зелёный', () => {
    const next = applyPowerState(items, { id: 'cell-2', status: 'on', grounded: true })
    expect(next[1].status).toBe('on')
    expect(next[1].grounded).toBe(true)
    expect(powerStateOf(next[1].status, next[1].grounded).color).toBe('#22C55E')
  })

  it('возвращает тот же массив, если состояние не изменилось (без лишних перерисовок)', () => {
    expect(applyPowerState(items, { id: 'cell-1', status: 'off', grounded: false })).toBe(items)
    expect(applyPowerState(items, { id: 'missing', status: 'on', grounded: false })).toBe(items)
  })

  it('результат пригоден для немедленной перекраски: energized меняется на лету', () => {
    const next = applyPowerState(items, { id: 'cell-1', status: 'on', grounded: false })
    expect(isEnergized(next[0].status, next[0].grounded)).toBe(true)
    expect(powerStateOf(next[0].status, next[0].grounded).color).toBe('#F04438')
    const back = applyPowerState(next, { id: 'cell-1', status: 'off', grounded: false })
    expect(powerStateOf(back[0].status, back[0].grounded).color).toBe('#22C55E')
  })
})
