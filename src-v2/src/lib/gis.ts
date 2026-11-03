/** Клиент ГИС-реестра: типы объектов, объекты, подложка, путь питания. */

import { apiRequest } from './api'

export interface TypeRef {
  code: string
  name: string
  category: string
  icon: string | null
  color: string | null
}

export interface AssetPort {
  id: string
  code: string
  name: string
  kind: 'in' | 'out' | 'io'
  nominal_voltage_kv: number | null
  sort_order: number
}

export interface AssetType {
  id: string
  code: string
  name: string
  category: string
  icon: string | null
  color: string | null
  port_template: { ports?: Array<{ code: string; name: string; kind: string; voltage_kv?: number }> }
  attr_schema: Record<string, { type?: string }>
  required_attrs: string[]
  is_mobile_default: boolean
  sort_order: number
  is_active: boolean
  description: string | null
}

export interface AssetBrief {
  id: string
  code: string
  name: string
  type: TypeRef
  status: string
  is_mobile: boolean
  grounded: boolean
  x: number | null
  y: number | null
  location_text: string | null
  version: number
  updated_at: string
}

export interface AssetOut extends AssetBrief {
  pit_id: string
  lifecycle: string
  z: number | null
  lat: number | null
  lon: number | null
  attrs: Record<string, unknown>
  parent_id: string | null
  parent_name: string | null
  ports: AssetPort[]
}

export interface MapLayer {
  id: string
  name: string
  image_url: string
  width_px: number
  height_px: number
  meters_per_pixel: number
  width_m: number
  height_m: number
  bounds: [[number, number], [number, number]]
  min_zoom: number
  max_zoom: number
  version: number
}

export interface PowerPathNode {
  id: string | null
  code: string | null
  name: string
  type_code: string | null
  type_name: string | null
  role: string
  synthetic: boolean
}

export interface PowerPath {
  asset_id: string
  asset_name: string
  source: PowerPathNode | null
  chain: PowerPathNode[]
  note: string
}

export const gisApi = {
  types: () => apiRequest<AssetType[]>('/api/asset-types'),

  assets: (params: { type_code?: string; status?: string; is_mobile?: boolean; q?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.type_code) query.set('type_code', params.type_code)
    if (params.status) query.set('status', params.status)
    if (params.is_mobile !== undefined) query.set('is_mobile', String(params.is_mobile))
    if (params.q) query.set('q', params.q)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return apiRequest<{ items: AssetBrief[]; total: number }>(`/api/assets${suffix}`)
  },

  asset: (id: string) => apiRequest<AssetOut>(`/api/assets/${id}`),

  powerPath: (id: string) => apiRequest<PowerPath>(`/api/assets/${id}/power-path`),

  layer: () => apiRequest<MapLayer>('/api/map/layers/active'),

  create: (payload: {
    name: string
    type_code: string
    code?: string
    x: number
    y: number
    status?: string
    parent_id?: string | null
    location_text?: string | null
    attrs?: Record<string, unknown>
  }) => apiRequest<AssetOut>('/api/assets', { method: 'POST', body: JSON.stringify(payload) }),

  update: (id: string, payload: Record<string, unknown>) =>
    apiRequest<AssetOut>(`/api/assets/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  remove: (id: string) => apiRequest<{ message: string }>(`/api/assets/${id}`, { method: 'DELETE' }),
}

export const STATUS_LABEL: Record<string, string> = {
  on: 'под напряжением',
  off: 'обесточено',
  standby: 'резерв',
  maintenance: 'ремонт',
  decommissioned: 'списано',
}

export const STATUS_COLOR: Record<string, string> = {
  on: '#2FBF71',
  off: '#6B7A8A',
  standby: '#3D8BFD',
  maintenance: '#F5A524',
  decommissioned: '#F2545B',
}
