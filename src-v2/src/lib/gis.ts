/** Клиент ГИС: реестр, топология, схема, переключения, документы. */

import { apiRequest } from './api'

export interface TypeRef {
  code: string
  name: string
  category: string
  schema_symbol?: string
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
  schema_x?: number | null
  schema_y?: number | null
}

export interface AssetType {
  id: string
  code: string
  name: string
  category: string
  schema_symbol: string
  icon: string | null
  color: string | null
  port_template: { ports?: Array<{ code: string; name: string; kind: string; voltage_kv?: number }> }
  attr_schema: Record<string, { type?: string }>
  required_attrs: string[]
  is_mobile_default: boolean
  sort_order: number
  is_active: boolean
  description: string | null
  parent_id: string | null
  parent_name: string | null
  assets_count: number
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
  parent_id: string | null
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
  type_icon: string | null
  role: string
  synthetic: boolean
  link_id: string | null
  link_label: string | null
  link_state: string | null
}

export interface PowerPath {
  asset_id: string
  asset_name: string
  energized: boolean
  source: PowerPathNode | null
  chain: PowerPathNode[]
  reason: string | null
  note: string
}

export interface GraphNode {
  id: string
  code: string
  name: string
  type_code: string
  type_name: string
  type_icon: string | null
  type_color: string | null
  category: string
  schema_symbol: string
  status: string
  grounded: boolean
  energized: boolean
  is_source: boolean
  parent_id: string | null
  schema_x: number | null
  schema_y: number | null
  ports: AssetPort[]
}

export interface GraphBlockChild {
  id: string
  code: string
  name: string
  role: string | null
  local_x: number | null
  local_y: number | null
  type_name: string | null
  params: Record<string, unknown>
}

export interface SchemaBlock {
  id: string
  code: string
  name: string
  block_type: string
  icon: string | null
  asset_type_code: string | null
  nodes_count: number
  external_ports: number
  roles: string[]
}

export interface GraphBlock {
  asset_id: string
  code: string
  name: string
  block_code: string | null
  schema_x: number | null
  schema_y: number | null
  collapsed?: boolean
  children: GraphBlockChild[]
}

export interface GraphEdge {
  id: string
  from_asset_id: string
  to_asset_id: string
  label: string
  link_type: string
  state: string
  feed_role: string
  cable_mark: string | null
  length_m: number | null
  cross_section_mm2: number | null
  cores: number | null
  version: number
}

export interface TopologyGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  blocks: GraphBlock[]
}

export interface TopologyIssue {
  level: string
  code: string
  message: string
  asset_id: string | null
  link_id: string | null
}

export interface LinkOut {
  id: string
  from_asset: { id: string; code: string; name: string; type_code: string; type_icon: string | null; status: string }
  to_asset: { id: string; code: string; name: string; type_code: string; type_icon: string | null; status: string }
  from_port: { id: string; code: string; name: string; kind: string; voltage_kv: number | null }
  to_port: { id: string; code: string; name: string; kind: string; voltage_kv: number | null }
  link_type: string
  feed_role: string
  state: string
  cable_mark: string | null
  length_m: number | null
  cross_section_mm2: number | null
  cores: number | null
  line: { id: string; code: string; name: string } | null
  label: string
  version: number
  warnings: string[]
}

export interface DocumentOut {
  id: string
  asset_id: string
  doc_type: string
  doc_type_label: string
  title: string
  file_name: string
  mime: string
  size_bytes: number
  version: string | null
  created_at: string
  content_url: string
  sha256: string | null
}

export interface ChildAsset {
  id: string
  code: string
  name: string
  type_code: string
  type_icon: string | null
  type_name: string
  status: string
  grounded: boolean
  energized: boolean
  ports: AssetPort[]
}

export const gisApi = {
  types: () => apiRequest<AssetType[]>('/api/asset-types'),

  assets: (params: {
    type_code?: string
    status?: string
    is_mobile?: boolean
    parent_id?: string
    q?: string
  } = {}) => {
    const query = new URLSearchParams()
    if (params.type_code) query.set('type_code', params.type_code)
    if (params.status) query.set('status', params.status)
    if (params.is_mobile !== undefined) query.set('is_mobile', String(params.is_mobile))
    if (params.parent_id) query.set('parent_id', params.parent_id)
    if (params.q) query.set('q', params.q)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return apiRequest<{ items: AssetBrief[]; total: number }>(`/api/assets${suffix}`)
  },

  asset: (id: string) => apiRequest<AssetOut>(`/api/assets/${id}`),

  children: (id: string) => apiRequest<ChildAsset[]>(`/api/assets/${id}/children`),

  powerPath: (id: string) => apiRequest<PowerPath>(`/api/assets/${id}/power-path`),

  layer: () => apiRequest<MapLayer>('/api/map/layers/active'),

  uploadMap: (
    file: File,
    params: { name: string; meters_per_pixel: number; origin_x: number; origin_y: number },
  ) => {
    const form = new FormData()
    form.append('file', file)
    form.append('name', params.name)
    form.append('meters_per_pixel', String(params.meters_per_pixel))
    form.append('origin_x', String(params.origin_x))
    form.append('origin_y', String(params.origin_y))
    return apiRequest<MapLayer>('/api/map/layers', { method: 'POST', body: form })
  },

  create: (payload: {
    name: string
    type_code: string
    code?: string
    x?: number | null
    y?: number | null
    status?: string
    parent_id?: string | null
    location_text?: string | null
    attrs?: Record<string, unknown>
  }) => apiRequest<AssetOut>('/api/assets', { method: 'POST', body: JSON.stringify(payload) }),

  update: (id: string, payload: Record<string, unknown>) =>
    apiRequest<AssetOut>(`/api/assets/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  remove: (id: string) => apiRequest<{ message: string }>(`/api/assets/${id}`, { method: 'DELETE' }),

  setState: (id: string, payload: { status?: string; grounded?: boolean; reason?: string }) =>
    apiRequest<{ asset: AssetOut; energization_changed: boolean; affected_assets: number }>(
      `/api/assets/${id}/state`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),

  graph: () => apiRequest<TopologyGraph>('/api/topology/graph'),

  issues: () => apiRequest<TopologyIssue[]>('/api/topology/issues'),

  links: (params: { asset_id?: string; state?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.asset_id) query.set('asset_id', params.asset_id)
    if (params.state) query.set('state', params.state)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return apiRequest<{ items: LinkOut[]; total: number }>(`/api/links${suffix}`)
  },

  createLink: (payload: {
    from_port_id: string
    to_port_id: string
    link_type?: string
    feed_role?: string
    state?: string
    line_id?: string | null
    cable_mark?: string | null
    length_m?: number | null
    cross_section_mm2?: number | null
    cores?: number | null
  }) => apiRequest<LinkOut>('/api/links', { method: 'POST', body: JSON.stringify(payload) }),

  updateLink: (id: string, payload: Record<string, unknown>) =>
    apiRequest<LinkOut>(`/api/links/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  deleteLink: (id: string) =>
    apiRequest<{ message: string }>(`/api/links/${id}`, { method: 'DELETE' }),

  lines: () => apiRequest<Array<{ id: string; code: string; name: string }>>('/api/lines'),

  documents: (assetId: string) =>
    apiRequest<{ items: DocumentOut[]; total: number }>(`/api/assets/${assetId}/documents`),

  uploadDocument: async (assetId: string, file: File, docType: string, title: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('doc_type', docType)
    if (title) form.append('title', title)
    return apiRequest<DocumentOut>(`/api/assets/${assetId}/documents`, {
      method: 'POST',
      body: form,
    })
  },

  deleteDocument: (id: string) =>
    apiRequest<{ message: string }>(`/api/documents/${id}`, { method: 'DELETE' }),

  getSchemaFrame: () =>
    apiRequest<SchemaFrame>('/api/topology/frame'),

  saveSchemaFrame: (payload: Record<string, unknown>) =>
    apiRequest<SchemaFrame>('/api/topology/frame', { method: 'PUT', body: JSON.stringify(payload) }),

  createType: (payload: Record<string, unknown>) =>
    apiRequest<AssetType>('/api/asset-types', { method: 'POST', body: JSON.stringify(payload) }),

  updateType: (id: string, payload: Record<string, unknown>) =>
    apiRequest<AssetType>(`/api/asset-types/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  deleteType: (id: string) =>
    apiRequest<AssetType>(`/api/asset-types/${id}`, { method: 'DELETE' }),

  saveSchemaLayout: (
    items: Array<{ asset_id: string; x: number; y: number }>,
    ports: Array<{ port_id: string; x: number; y: number }> = [],
  ) =>
    apiRequest<{ updated: number; updated_ports: number; skipped: string[] }>('/api/topology/layout', {
      method: 'PUT',
      body: JSON.stringify({ items, ports }),
    }),

  allTypes: () => apiRequest<AssetType[]>('/api/asset-types?include_inactive=true'),
schemaBlocks: () => apiRequest<SchemaBlock[]>('/api/schema/blocks'),

  instantiateBlock: (code: string, x: number, y: number, name?: string) =>
    apiRequest<{ asset_id: string; code: string; children: number; block_code: string }>(
      `/api/schema/blocks/${code}/instantiate`,
      { method: 'POST', body: JSON.stringify({ x, y, name }) },
    ),

schemaLegend: () =>
    apiRequest<{ symbol: string; title: string; count: number }[]>('/api/schema/legend'),

  collapseBlock: (assetId: string, collapsed: boolean) =>
    apiRequest<{ asset_id: string; collapsed: boolean }>(
      `/api/schema/assets/${assetId}/collapse`,
      { method: 'POST', body: JSON.stringify({ collapsed }) },
    ),

  deleteBlockCell: (assetId: string, cellId: string) =>
    apiRequest<{ message: string; id: string }>(
      `/api/schema/assets/${assetId}/cells/${cellId}`,
      { method: 'DELETE' },
    ),

  createJumper: (assetId: string, fromCellId: string, toCellId: string, label?: string) =>
    apiRequest<{ id: string; from: string; to: string }>(
      `/api/schema/assets/${assetId}/jumpers`,
      { method: 'POST', body: JSON.stringify({ from_cell_id: fromCellId, to_cell_id: toCellId, label }) },
    ),

  addBlockCell: (assetId: string, label: string, role = 'outgoing') =>
    apiRequest<{ id: string; code: string; name: string; role: string }>(
      `/api/schema/assets/${assetId}/cells`,
      { method: 'POST', body: JSON.stringify({ label, role }) },
    ),

}

export interface SchemaFrame {
  sheet_format: string
  organization: string
  department: string
  object_name: string
  sheet: string
  scale: string
  developed_by: string
  checked_by: string
  approved_by: string
  date: string
  show_on_screen: boolean
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

export const DOC_TYPE_LABEL: Record<string, string> = {
  schematic: 'Электросхема',
  settings: 'Уставки',
  manual: 'Инструкция',
  other: 'Прочее',
}
