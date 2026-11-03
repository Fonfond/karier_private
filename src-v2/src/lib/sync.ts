/** Отправка офлайн-очереди на сервер. */

import { mapId, markFailed, getBlob, listOps, removeOp, resolveId } from './outbox'
import type { OutboxOp } from './outbox'
import { opsApi } from './opsApi'
import type { PhotoResult } from './photo'

export interface SyncResult {
  sent: number
  failed: number
  remaining: number
}

interface PhotoPayloadMeta {
  capturedAt: string
  geo: { lat: number; lon: number; accuracy: number | null; source: 'exif' | 'device' | 'asset' | 'manual' | 'none' }
  exif: Record<string, unknown>
  width: number
  height: number
  watermark: string
}

function restorePhoto(blob: Blob, meta: PhotoPayloadMeta): PhotoResult {
  return {
    blob,
    width: meta.width,
    height: meta.height,
    capturedAt: new Date(meta.capturedAt),
    geo: meta.geo,
    exif: meta.exif,
    watermark: meta.watermark,
  }
}

async function processOp(op: OutboxOp): Promise<void> {
  const payload = op.payload as Record<string, any>

  if (op.kind === 'inspection_create') {
    const created = await opsApi.createInspection({
      kind: payload.kind ?? 'walk',
      title: payload.title ?? undefined,
      asset_ids: payload.asset_ids ?? [],
    })
    await mapId(payload.tempId ?? op.id, created.id)
    return
  }

  if (op.kind === 'inspection_item') {
    const inspectionId = await resolveId(payload.inspectionId)
    await opsApi.setItem(inspectionId, {
      asset_id: payload.asset_id,
      result: payload.result,
      comment: payload.comment ?? undefined,
    })
    return
  }

  if (op.kind === 'inspection_submit') {
    const inspectionId = await resolveId(payload.inspectionId)
    try {
      await opsApi.submitInspection(inspectionId)
    } catch (error) {
      const message = error instanceof Error ? error.message : ''
      // обход уже отправлен — не считаем ошибкой
      if (!message.includes('409')) throw error
    }
    return
  }

  if (op.kind === 'media') {
    const blob = await getBlob(op.id)
    if (!blob) return
    await opsApi.uploadPhoto(
      payload.assetId,
      restorePhoto(blob, payload.meta),
      payload.purpose ?? 'inspection',
      {
        inspectionId: payload.inspectionId ? await resolveId(payload.inspectionId) : undefined,
        defectId: payload.defectId ? await resolveId(payload.defectId) : undefined,
      },
    )
    return
  }

  if (op.kind === 'defect') {
    let photoId: string | undefined
    const blob = await getBlob(op.id)
    if (blob && payload.photo) {
      const media = await opsApi.uploadPhoto(
        payload.assetId,
        restorePhoto(blob, payload.photo),
        'defect',
        { inspectionId: payload.inspectionId ? await resolveId(payload.inspectionId) : undefined },
      )
      photoId = media.id
    }
    await opsApi.createDefect({
      asset_id: payload.assetId,
      severity: payload.severity,
      description: payload.description,
      category: payload.category ?? undefined,
      inspection_id: payload.inspectionId ? await resolveId(payload.inspectionId) : undefined,
      photo_before_id: photoId,
    })
    return
  }
}

/** Последовательно отправить очередь. Останавливается на первой сетевой ошибке. */
export async function syncOutbox(): Promise<SyncResult> {
  if (typeof navigator !== 'undefined' && !navigator.onLine) {
    const remaining = (await listOps()).length
    return { sent: 0, failed: 0, remaining }
  }

  const ops = await listOps()
  let sent = 0
  let failed = 0

  for (const op of ops) {
    if (op.attempts >= 5) {
      failed += 1
      continue
    }
    try {
      await processOp(op)
      await removeOp(op.id)
      sent += 1
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      const isNetwork = message.includes('Сервер недоступен') || message.includes('Failed to fetch')
      await markFailed(op.id, message)
      if (isNetwork) break
      failed += 1
    }
  }

  const remaining = (await listOps()).length
  return { sent, failed, remaining }
}
