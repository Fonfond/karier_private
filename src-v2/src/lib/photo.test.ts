import { describe, expect, it } from 'vitest'
import { buildWatermarkLines, formatCoords, watermarkText } from './photo'

const meta = { assetCode: 'KTP-14', authorName: 'Иванов Иван', authorTabNo: '000001' }

describe('водяной знак', () => {
  it('содержит дату, координаты, автора и код объекта', () => {
    const date = new Date('2026-11-03T09:15:00+08:00')
    const lines = buildWatermarkLines(
      date,
      { lat: 56.1234567, lon: 101.7654321, accuracy: 8.4, source: 'exif' },
      meta,
    )

    expect(lines).toHaveLength(3)
    expect(lines[0]).toContain('03.11.2026')
    expect(lines[0]).toContain('09:15')
    expect(lines[1]).toContain('56.123457')
    expect(lines[1]).toContain('101.765432')
    expect(lines[1]).toContain('±8')
    expect(lines[1]).toContain('KTP-14')
    expect(lines[2]).toBe('Иванов Иван · таб. 000001')
  })

  it('честно сообщает об отсутствии координат', () => {
    const geo = { lat: 0, lon: 0, accuracy: null, source: 'none' as const }
    expect(formatCoords(geo)).toBe('координаты недоступны')

    const lines = buildWatermarkLines(new Date('2026-11-03T09:15:00+08:00'), geo, meta)
    expect(lines[1]).toContain('координаты недоступны')
    expect(lines[1]).not.toContain('0.000000')
  })

  it('склеивает строки в одну запись для БД', () => {
    const text = watermarkText(
      new Date('2026-11-03T09:15:00+08:00'),
      { lat: 56.1, lon: 101.2, accuracy: 12, source: 'device' },
      meta,
    )
    expect(text).toMatch(/^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}/)
    expect(text).toContain('56.100000, 101.200000 ±12 м')
    expect(text).toContain('KTP-14')
    expect(text).toContain('Иванов Иван · таб. 000001')
  })
})
