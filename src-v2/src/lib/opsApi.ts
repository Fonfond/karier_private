/** Клиент обходов, дефектов и фото. */

import { apiRequest } from './api'
import type { PhotoResult } from './photo'

export interface MediaItem {
  id: string
  asset_id: string | null
  inspection_id: string | null
  defect_id: string | null
  purpose: string
  mime: string
  size_bytes: number
  width: number | null
  height: number | null
  sha256: string | null
  captured_at: string | null
  lat: number | null
  lon: number | null
  accuracy_m: number | null
  geo_source: string
  author_tab_no: string | null
  author_name: string | null
  watermark_applied: string | null
  content_url: string
}

export interface InspectionItem {
  id: string
  asset: { id: string; code: string; name: string; type_code: string; type_icon: string | null }
  result: string | null
  comment: string | null
  checked_at: string | null
  media_count: number
}

export interface Inspection {
  id: string
  kind: string
  status: string
  title: string | null
  employee_id: string | null
  employee_name: string | null
  started_at: string
  finished_at: string | null
  submitted_at: string | null
  note: string | null
  total: number
  checked: number
  defects: number
  items: InspectionItem[]
}

export interface Defect {
  id: string
  asset: { id: string; code: string; name: string; type_code: string; type_icon: string | null }
  inspection_id: string | null
  severity: string
  status: string
  category: string | null
  description: string
  detected_at: string
  detected_by_name: string | null
  fixed_at: string | null
  fixed_by_name: string | null
  photo_before: MediaItem | null
  photo_after: MediaItem | null
  photo_count: number
}

export interface HistoryEntry {
  kind: string
  at: string
  title: string
  detail: string | null
  status: string | null
  severity: string | null
  media_id: string | null
  author: string | null
}

function photoForm(assetId: string, photo: PhotoResult, purpose: string, extra: {
  inspectionId?: string
  defectId?: string
}): FormData {
  const form = new FormData()
  form.append('file', photo.blob, `photo-${Date.now()}.jpg`)
  form.append('purpose', purpose)
  form.append('captured_at', photo.capturedAt.toISOString())
  form.append('geo_source', photo.geo.source)
  if (photo.geo.source !== 'none') {
    form.append('lat', String(photo.geo.lat))
    form.append('lon', String(photo.geo.lon))
    if (photo.geo.accuracy) form.append('accuracy_m', String(photo.geo.accuracy))
  }
  form.append('width', String(photo.width))
  form.append('height', String(photo.height))
  form.append('watermark', photo.watermark)
  form.append('exif', JSON.stringify(photo.exif ?? {}))
  if (extra.inspectionId) form.append('inspection_id', extra.inspectionId)
  if (extra.defectId) form.append('defect_id', extra.defectId)
  void assetId
  return form
}

export const opsApi = {
  uploadPhoto: (
    assetId: string,
    photo: PhotoResult,
    purpose: string,
    extra: { inspectionId?: string; defectId?: string } = {},
  ) =>
    apiRequest<MediaItem>(`/api/assets/${assetId}/media`, {
      method: 'POST',
      body: photoForm(assetId, photo, purpose, extra),
    }),

  photos: (assetId: string) =>
    apiRequest<{ items: MediaItem[]; total: number }>(`/api/assets/${assetId}/media`),

  deletePhoto: (id: string) =>
    apiRequest<{ message: string }>(`/api/media/${id}`, { method: 'DELETE' }),

  createInspection: (payload: { kind?: string; title?: string; asset_ids: string[] }) =>
    apiRequest<Inspection>('/api/inspections', { method: 'POST', body: JSON.stringify(payload) }),

  inspections: (mine = true) =>
    apiRequest<{ items: Inspection[]; total: number }>(`/api/inspections?mine=${mine}`),

  inspection: (id: string) => apiRequest<Inspection>(`/api/inspections/${id}`),

  setItem: (inspectionId: string, payload: { asset_id: string; result: string; comment?: string }) =>
    apiRequest<Inspection>(`/api/inspections/${inspectionId}/items`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  submitInspection: (id: string) =>
    apiRequest<Inspection>(`/api/inspections/${id}/submit`, { method: 'POST' }),

  deleteDefect: (id: string) =>
    apiRequest<{ message: string; id: string }>(`/api/defects/${id}`, { method: 'DELETE' }),

  createDefect: (payload: {
    asset_id: string
    severity: string
    description: string
    category?: string
    inspection_id?: string
    photo_before_id?: string
  }) => apiRequest<Defect>('/api/defects', { method: 'POST', body: JSON.stringify(payload) }),

  defects: (params: { status?: string; severity?: string; asset_id?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.status) query.set('status', params.status)
    if (params.severity) query.set('severity', params.severity)
    if (params.asset_id) query.set('asset_id', params.asset_id)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return apiRequest<{ items: Defect[]; total: number }>(`/api/defects${suffix}`)
  },

  updateDefect: (id: string, payload: Record<string, unknown>) =>
    apiRequest<Defect>(`/api/defects/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  history: (assetId: string) =>
    apiRequest<{ asset_id: string; items: HistoryEntry[] }>(`/api/assets/${assetId}/history`),
}

export const SEVERITY_LABEL: Record<string, string> = {
  low: 'низкая',
  medium: 'средняя',
  high: 'высокая',
  critical: 'критичная',
}

export const SEVERITY_COLOR: Record<string, string> = {
  low: '#6B7A8A',
  medium: '#4C9AFF',
  high: '#F5A524',
  critical: '#F2545B',
}

export const DEFECT_STATUS_LABEL: Record<string, string> = {
  open: 'открыт',
  in_progress: 'в работе',
  fixed: 'устранён',
  accepted: 'принят',
  rejected: 'отклонён',
}

export const RESULT_LABEL: Record<string, string> = {
  ok: 'норма',
  defect: 'дефект',
  critical: 'критично',
  not_found: 'не найден',
  no_access: 'нет доступа',
}
