/** Фото: EXIF, геоданные, водяной знак на canvas и подготовка к загрузке. */

import exifr from 'exifr'

export interface PhotoMeta {
  assetCode: string
  authorName: string
  authorTabNo: string
}

export interface GeoPoint {
  lat: number
  lon: number
  accuracy: number | null
  source: 'exif' | 'device' | 'asset' | 'manual' | 'none'
}

export interface PhotoResult {
  blob: Blob
  width: number
  height: number
  capturedAt: Date
  geo: GeoPoint
  exif: Record<string, unknown>
  watermark: string
}

const DATE_FMT = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

export function formatCapturedAt(date: Date): string {
  return DATE_FMT.format(date).replace(',', '')
}

export function formatCoords(geo: GeoPoint): string {
  if (geo.source === 'none' || geo.lat === 0 || geo.lon === 0) return 'координаты недоступны'
  const accuracy = geo.accuracy ? ` ±${Math.round(geo.accuracy)} м` : ''
  return `${geo.lat.toFixed(6)}, ${geo.lon.toFixed(6)}${accuracy}`
}

/**
 * Строки водяного знака. Вынесено отдельной функцией, чтобы покрыть тестами:
 * на фото должны попасть дата/время, координаты, автор и код объекта.
 */
export function buildWatermarkLines(
  capturedAt: Date,
  geo: GeoPoint,
  meta: PhotoMeta,
): [string, string, string] {
  const author = `${meta.authorName} · таб. ${meta.authorTabNo}`
  return [formatCapturedAt(capturedAt), `${formatCoords(geo)} · ${meta.assetCode}`, author]
}

export function watermarkText(capturedAt: Date, geo: GeoPoint, meta: PhotoMeta): string {
  return buildWatermarkLines(capturedAt, geo, meta).join(' · ')
}

/** Прочитать EXIF: дата съёмки, GPS, модель устройства. */
export async function readExif(file: File): Promise<Record<string, unknown>> {
  try {
    const data = await exifr.parse(file, {
      gps: true,
      pick: ['DateTimeOriginal', 'CreateDate', 'Make', 'Model', 'latitude', 'longitude', 'GPSAltitude'],
    })
    if (!data) return {}
    return {
      DateTimeOriginal: data.DateTimeOriginal instanceof Date ? data.DateTimeOriginal.toISOString() : data.DateTimeOriginal,
      CreateDate: data.CreateDate instanceof Date ? data.CreateDate.toISOString() : data.CreateDate,
      Make: data.Make,
      Model: data.Model,
      latitude: data.latitude,
      longitude: data.longitude,
    }
  } catch {
    return {}
  }
}

/** Геолокация устройства (если EXIF без GPS). */
export function readDeviceGeo(timeoutMs = 6000): Promise<GeoPoint | null> {
  if (!('geolocation' in navigator)) return Promise.resolve(null)
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), timeoutMs)
    navigator.geolocation.getCurrentPosition(
      (position) => {
        clearTimeout(timer)
        resolve({
          lat: position.coords.latitude,
          lon: position.coords.longitude,
          accuracy: position.coords.accuracy ?? null,
          source: 'device',
        })
      },
      () => {
        clearTimeout(timer)
        resolve(null)
      },
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 60000 },
    )
  })
}

function loadImage(blob: Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob)
    const image = new Image()
    image.onload = () => {
      URL.revokeObjectURL(url)
      resolve(image)
    }
    image.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('Не удалось прочитать изображение'))
    }
    image.src = url
  })
}

/** Наложить водяной знак и вернуть готовый JPEG. */
export async function applyWatermark(
  file: File,
  capturedAt: Date,
  geo: GeoPoint,
  meta: PhotoMeta,
  maxWidth = 1600,
): Promise<{ blob: Blob; width: number; height: number; watermark: string }> {
  const image = await loadImage(file)
  const scale = Math.min(1, maxWidth / image.naturalWidth)
  const width = Math.round(image.naturalWidth * scale)
  const height = Math.round(image.naturalHeight * scale)

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('Canvas недоступен')

  ctx.drawImage(image, 0, 0, width, height)

  const lines = buildWatermarkLines(capturedAt, geo, meta)
  const base = Math.max(12, Math.round(width / 55))
  const fontSize = Math.round(base * 1.05)
  const lineHeight = Math.round(fontSize * 1.45)
  const padding = Math.round(fontSize * 0.9)
  const barHeight = padding * 2 + lineHeight * lines.length

  ctx.fillStyle = 'rgba(4, 9, 14, 0.62)'
  ctx.fillRect(0, height - barHeight, width, barHeight)

  ctx.fillStyle = 'rgba(76, 154, 255, 0.95)'
  ctx.fillRect(0, height - barHeight, Math.round(width * 0.012) + 4, barHeight)

  ctx.textBaseline = 'top'
  lines.forEach((line, index) => {
    ctx.font =
      index === 0
        ? `600 ${Math.round(fontSize * 1.15)}px -apple-system, Segoe UI, Roboto, sans-serif`
        : `500 ${fontSize}px -apple-system, Segoe UI, Roboto, sans-serif`
    ctx.fillStyle = index === 0 ? '#ffffff' : 'rgba(230, 237, 243, 0.86)'
    ctx.fillText(line, padding, height - barHeight + padding + index * lineHeight)
  })

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (result) => (result ? resolve(result) : reject(new Error('Не удалось сжать фото'))),
      'image/jpeg',
      0.86,
    )
  })

  return { blob, width, height, watermark: watermarkText(capturedAt, geo, meta) }
}

/** Полный конвейер: EXIF → гео → водяной знак. */
export async function processPhoto(
  file: File,
  meta: PhotoMeta,
  fallbackGeo?: GeoPoint | null,
): Promise<PhotoResult> {
  const exif = await readExif(file)

  const exifDate = typeof exif.DateTimeOriginal === 'string' ? new Date(exif.DateTimeOriginal) : null
  const capturedAt = exifDate && !Number.isNaN(exifDate.getTime()) ? exifDate : new Date()

  let geo: GeoPoint | null = null
  if (typeof exif.latitude === 'number' && typeof exif.longitude === 'number') {
    geo = { lat: exif.latitude, lon: exif.longitude, accuracy: null, source: 'exif' }
  }
  if (!geo) geo = await readDeviceGeo()
  if (!geo && fallbackGeo) geo = fallbackGeo
  if (!geo) geo = { lat: 0, lon: 0, accuracy: null, source: 'none' }

  const marked = await applyWatermark(file, capturedAt, geo, meta)
  return {
    blob: marked.blob,
    width: marked.width,
    height: marked.height,
    capturedAt,
    geo,
    exif,
    watermark: marked.watermark,
  }
}

export async function sha256Hex(blob: Blob): Promise<string> {
  const buffer = await blob.arrayBuffer()
  const digest = await crypto.subtle.digest('SHA-256', buffer)
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}
