import { describe, expect, it } from 'vitest'
import { buildDxf } from './dxf'

const nodes = [
  {
    id: 'a',
    code: 'PS-356',
    name: 'ПС-35/6 кВ',
    x: 0,
    y: 0,
    width: 210,
    height: 84,
    ports: [{ id: 'p1', code: 'OUT-1', fx: 1, fy: 0.5 }],
  },
  {
    id: 'b',
    code: 'KTP-14',
    name: 'КТП-14',
    x: 300,
    y: 120,
    width: 210,
    height: 84,
    ports: [{ id: 'p2', code: 'IN-1', fx: 0, fy: 0.5 }],
  },
]

const edges = [{ from: { x: 0, y: 0 }, to: { x: 300, y: 120 }, label: 'КЛ-6 кВ' }]

describe('DXF экспорт схемы', () => {
  it('формирует корректный R12-файл с узлами, портами и линиями', () => {
    const dxf = buildDxf(nodes, edges)

    expect(dxf.startsWith('0\nSECTION\n2\nHEADER')).toBe(true)
    expect(dxf).toContain('AC1009')
    expect(dxf.trimEnd().endsWith('0\nEOF')).toBe(true)

    const lines = dxf.match(/\nLINE\n/g) ?? []
    // 4 линии рамки на узел + одна линия связи
    expect(lines.length).toBe(4 * nodes.length + 1)

    expect((dxf.match(/\nCIRCLE\n/g) ?? []).length).toBe(2)
    expect((dxf.match(/\nTEXT\n/g) ?? []).length).toBeGreaterThanOrEqual(4)

    expect(dxf).toContain('PS-356')
    expect(dxf).toContain('KTP-14')
    expect(dxf).toContain('КЛ-6 кВ')
  })

  it('инвертирует ось Y, чтобы схема не была перевёрнутой', () => {
    const dxf = buildDxf([nodes[0]], [])
    const match = dxf.match(/10\n([\d.]+)\n20\n([\d.]+)/)
    expect(match).not.toBeNull()
    // верхняя граница узла лежит выше нижней после инверсии
    expect(Number(match![2])).toBeGreaterThan(0)
  })

  it('пустая схема даёт валидный пустой файл', () => {
    const dxf = buildDxf([], [])
    expect(dxf).toContain('ENTITIES')
    expect(dxf.trimEnd().endsWith('0\nEOF')).toBe(true)
  })
})
