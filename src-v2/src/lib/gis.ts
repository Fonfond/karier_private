/** Клиент ГИС: реестр, топология, схема, переключения, документы. */

import { apiRequest, requestBlob } from './api'

export interface TypeRef {
  code: string
  name: string
  category: string
  schema_symbol?: string
  has_maintenance?: boolean
  is_composite?: boolean
  /**
   * Шаблон состава. В v2 (этап 2) — массив: метаданные + секции с ячейками;
   * для legacy-типов — плоский список `{type_code, count}`. Разбор — `lib/equipmentTemplates.ts`.
   */
  composite_template?: unknown
  /** Класс оборудования (`distribution`, `switching`, `cell`, `cable`…) — этап 1. */
  equipment_class?: string
  group_code?: string | null
  icon: string | null
  color: string | null
}

/** Вид ячейки ПС/БКРУ (`gis.assets.cell_kind`, миграция 0015). */
export type CellKind = 'in' | 'out' | 'sectional'

/** Кабельный учёт этапа 2 (`gis.assets.lifecycle_status`). */
export type CableState = 'installed' | 'reserve' | 'repair'

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

/** Типы данных поля паспорта (`gis.asset_type_fields.data_type`). */
export type AssetFieldDataType = 'number' | 'integer' | 'text' | 'boolean' | 'date' | 'select'

/**
 * Поле паспорта типа оборудования. Отдаётся в `GET /api/asset-types?with_fields=1`
 * и `GET /api/asset-types/{id}/fields`; из него строится динамическая форма реестра.
 */
export interface AssetTypeField {
  id?: string
  code: string
  label: string
  unit?: string | null
  data_type: AssetFieldDataType
  required?: boolean
  default_value?: unknown
  options?: Array<string | number | boolean>
  min?: number | null
  max?: number | null
  group_label?: string | null
  sort_order?: number
}

export interface AssetType {
  id: string
  code: string
  name: string
  category: string
  /** Класс оборудования (миграция 0015): вкладки создания по классам. */
  equipment_class?: string
  /** Код вкладки UI для класса (`distribution`, `transformers`, `cells`…). */
  group_code?: string | null
  schema_symbol: string
  has_maintenance?: boolean
  is_composite?: boolean
  /**
   * Состав комплекта. v2 (этап 2) — массив: метаданные + секции с ячейками;
   * legacy v1 — плоский список `{type_code, count, label}`. Форма «Типы» читает
   * только legacy-элементы, v2-шаблон она не перезаписывает (см. TypesPage).
   */
  composite_template?:
    | Array<{ type_code?: string; count?: number; label?: string; [key: string]: unknown }>
    | Record<string, unknown>
    | null
  icon: string | null
  color: string | null
  port_template: { ports?: Array<{ code: string; name: string; kind: string; voltage_kv?: number }> }
  /** legacy-схема атрибутов: правила `{type, unit, options, min, max, label…}`. */
  attr_schema: Record<string, Record<string, unknown>>
  required_attrs: string[]
  /** Поля паспорта: заполняются только при `with_fields=1`. */
  fields?: AssetTypeField[]
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
  grouped?: boolean
  /** Ячейка/разъединитель: вид и номер (этап 2 модели оборудования). */
  cell_kind?: CellKind | null
  cell_no?: number | null
  section_no?: number | null
  /** Кабель: на оборудовании / в запасе / в ремонте. */
  lifecycle_status?: CableState | null
  version: number
  updated_at: string
}

export interface AssetOut extends AssetBrief {
  schema_x?: number | null
  schema_y?: number | null
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

/**
 * Подложка карты защищена авторизацией (S-5): качаем её тем же access-токеном
 * и отдаём Leaflet blob-URL. Вызывающий обязан сделать URL.revokeObjectURL.
 */
export async function layerImageObjectUrl(imageUrl: string): Promise<string> {
  return URL.createObjectURL(await requestBlob(imageUrl))
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

export interface GraphJumper {
  id: string
  from_cell_id: string
  to_cell_id: string
  label: string | null
}

export interface GraphBlock {
  kind?: string | null
  /** исторические поля: то же значение, что schema_width/schema_height */
  width?: number | null
  height?: number | null
  /** этап 3: gis.assets.schema_width / schema_height (px), задаются NodeResizer'ом */
  schema_width?: number | null
  schema_height?: number | null
  asset_id: string
  code: string
  name: string
  block_code: string | null
  schema_x: number | null
  schema_y: number | null
  collapsed?: boolean
  jumpers?: GraphJumper[]
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
  cable_no?: string | null
  cable_status?: string
  installed_on?: string | null
  route_note?: string | null
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

/**
 * Одна запись PUT /api/topology/layout (этап 3). Все поля, кроме `asset_id`,
 * необязательны: узел/блок присылает x/y (и width/height), ячейка внутри блока —
 * local_x/local_y (`gis.assets.schema_local_x/y`).
 */
export interface SchemaLayoutItem {
  asset_id: string
  x?: number
  y?: number
  width?: number
  height?: number
  local_x?: number
  local_y?: number
}

export interface SchemaLayoutPortItem {
  port_id: string
  x: number
  y: number
}

export interface SchemaLayoutResult {
  updated: number
  updated_ports: number
  updated_blocks?: number
  updated_cells?: number
  skipped: string[]
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
  cable_no?: string | null
  cable_status?: string
  installed_on?: string | null
  /** Кабель-объект, установленный на участок (этап 2, nullable). */
  cable_asset_id?: string | null
  cable_asset?: CableAssetRef | null
  route_note?: string | null
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
  /** Придут на будущих версиях API; сейчас вид/номер берём из имени и params. */
  cell_kind?: CellKind | null
  cell_no?: number | null
  section_no?: number | null
  ports: AssetPort[]
}

// --- этап 2: составные устройства, переключение, кабельный учёт -------------

/** Созданная ячейка блока (ответ `POST /api/schema/composite`). */
export interface CompositeCellResult {
  id: string
  code: string
  name: string
  type_code: string
  cell_kind: CellKind
  cell_no: number
  section_no: number
  status: string
  grounded: boolean
  voltage_kv: number | null
  local_x: number | null
  local_y: number | null
}

export interface CompositeSectionResult {
  section_no: number
  label: string
  voltage_kv: number | null
  cells: CompositeCellResult[]
}

export interface CompositeDisconnectorResult {
  id: string
  code: string
  name: string
  type_code: string
  cell_kind: CellKind
  status: string
  grounded: boolean
}

export interface CompositeCreateResult {
  id: string
  code: string
  name: string
  type_code: string
  schema_x: number | null
  schema_y: number | null
  template_version: number
  children: number
  block: { id: string; code: string; name: string; type_code: string; schema_x: number | null; schema_y: number | null } | null
  sections: CompositeSectionResult[]
  cells: CompositeCellResult[]
  /** КТП: ячеек нет, только вводной разъединитель. */
  disconnector: CompositeDisconnectorResult | null
  disconnector_id: string | null
}

/** Ответ `POST /api/assets/{id}/toggle` — оперативное состояние ячейки/разъединителя. */
export interface ToggleResult {
  asset_id: string
  code: string
  name: string
  cell_kind: CellKind | null
  status: 'on' | 'off'
  previous_status: string
  changed: boolean
  grounded: boolean
  /** Оперативное «под напряжением»: включено и не заземлено (для цвета). */
  energized: boolean
  /** Фактическое напряжение: номинал при включении, иначе 0. */
  voltage_kv: number
  nominal_voltage_kv: number | null
  topology_energized: boolean
}

export interface CableAssetRef {
  id: string
  code: string
  name: string
  type_code: string
  type_icon: string | null
  status: string
}

/** Кабель-объект в кабельном учёте (`GET /api/cables`). */
export interface CableRecord {
  id: string
  code: string
  name: string
  type_code: string
  status: string
  lifecycle_status: CableState
  cable_mark: string | null
  section_mm2: number | null
  length_m: number | null
  voltage_kv: number | null
  /** Привязка: участок связи, на котором стоит кабель. */
  link_id: string | null
  link_label: string | null
  link_state: string | null
  installed_on: string | null
  from_asset: CableAssetRef | null
  to_asset: CableAssetRef | null
  attrs: Record<string, unknown>
  version: number
  updated_at: string
  warnings: string[]
}

export interface CableInstallResult {
  cable: CableRecord
  link_id: string | null
  link_label: string | null
}

export interface CableReturnResult {
  cable: CableRecord
  detached_links: string[]
}

export interface RelocateSchemaAssetIn {
  target_asset_id: string | null
  confirm?: boolean
  x?: number | null
  y?: number | null
  local_x?: number | null
  local_y?: number | null
}

export interface RelocateSchemaAssetOut {
  asset: AssetOut
  warnings: string[]
  old_parent_id: string | null
  old_block_id: string | null
  old_local_x: number | null
  old_local_y: number | null
  old_schema_x: number | null
  old_schema_y: number | null
}

export const gisApi = {
  /** Справочник типов; `with_fields` добавляет поля паспорта для динамической формы. */
  types: (params: { with_fields?: boolean; include_inactive?: boolean } = {}) => {
    const query = new URLSearchParams()
    if (params.with_fields) query.set('with_fields', '1')
    if (params.include_inactive) query.set('include_inactive', 'true')
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return apiRequest<AssetType[]>(`/api/asset-types${suffix}`)
  },

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
    /** Состояние кабеля: отдельная колонка `gis.assets.lifecycle_status` (0015). */
    lifecycle_status?: 'installed' | 'reserve' | 'repair'
  }) => apiRequest<AssetOut>('/api/assets', { method: 'POST', body: JSON.stringify(payload) }),

  update: (id: string, payload: Record<string, unknown>) =>
    apiRequest<AssetOut>(`/api/assets/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  remove: (id: string) => apiRequest<{ message: string }>(`/api/assets/${id}`, { method: 'DELETE' }),

  // Отмена удаления: объект возвращается из архива вместе со своими связями
  restoreAsset: (id: string) =>
    apiRequest<AssetOut>(`/api/assets/${id}/restore`, { method: 'POST' }),

  setState: (id: string, payload: { status?: string; grounded?: boolean; reason?: string }) =>
    apiRequest<{ asset: AssetOut; energization_changed: boolean; affected_assets: number }>(
      `/api/assets/${id}/state`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),

  /**
   * Этап 2: включить/отключить ячейку или разъединитель.
   * Без `state` — переключить (on→off, иначе on); с `state` — выставить.
   * В ответе `energized`/`voltage_kv` — для цвета и подписи «под напряжением».
   */
  toggleAsset: (id: string, payload: { state?: 'on' | 'off' | null; reason?: string } = {}) =>
    apiRequest<ToggleResult>(`/api/assets/${id}/toggle`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** Этап 2: блок + секции + ячейки (+ вводной разъединитель КТП) одной транзакцией. */
  createComposite: (payload: {
    type_code: string
    name: string
    x: number
    y: number
    code?: string | null
    cells_per_section?: number | null
  }) =>
    apiRequest<CompositeCreateResult>('/api/schema/composite', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** Этап 2: кабельный учёт — кабели-объекты по состоянию installed/reserve/repair. */
  cables: (params: { lifecycle_status?: CableState; q?: string; limit?: number } = {}) => {
    const query = new URLSearchParams()
    if (params.lifecycle_status) query.set('lifecycle_status', params.lifecycle_status)
    if (params.q) query.set('q', params.q)
    if (params.limit) query.set('limit', String(params.limit))
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return apiRequest<CableRecord[]>(`/api/cables${suffix}`)
  },

  /** Установить кабель: на участок связи (`link_id`) или на объект (`asset_id`). */
  installCable: (
    id: string,
    payload: {
      link_id?: string
      asset_id?: string
      cable_mark?: string
      length_m?: number
      cross_section_mm2?: number
      reason?: string
    },
  ) =>
    apiRequest<CableInstallResult>(`/api/cables/${id}/install`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** Снять кабель: в запас (`reserve`) или в ремонт (`repair`). */
  returnCable: (id: string, payload: { status?: CableState; link_id?: string; reason?: string } = {}) =>
    apiRequest<CableReturnResult>(`/api/cables/${id}/return`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

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

  // Отмена удаления связи: тот же id, те же порты
  restoreLink: (id: string) =>
    apiRequest<LinkOut>(`/api/links/${id}/restore`, { method: 'POST' }),

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
    items: SchemaLayoutItem[],
    ports: SchemaLayoutPortItem[] = [],
  ) =>
    apiRequest<SchemaLayoutResult>('/api/topology/layout', {
      method: 'PUT',
      body: JSON.stringify({ items, ports }),
    }),

groupAssets: (payload: { parent_type_code: string; name: string; child_ids: string[]; x?: number; y?: number }) =>
    apiRequest<{ parent_id: string; children: number }>('/api/asset-groups', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  ungroupAsset: (id: string) =>
    apiRequest<{ parent_id: string; children: number }>(`/api/asset-groups/${id}/ungroup`, { method: 'POST' }),

maintenanceList: (assetId: string) =>
    apiRequest<Array<{ id: string; at: string; kind: string; motor_hours: number | null; fuel_liters: number | null; fuel_level_pct: number | null; cost: number | null; note: string | null; author_name: string | null }>>(
      `/api/assets/${assetId}/maintenance`,
    ),

  maintenanceAdd: (assetId: string, payload: Record<string, unknown>) =>
    apiRequest<{ id: string }>(`/api/assets/${assetId}/maintenance`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  maintenanceDelete: (entryId: string) =>
    apiRequest<{ message: string }>(`/api/maintenance/${entryId}`, { method: 'DELETE' }),

ensurePorts: (assetId: string) =>
    apiRequest<{ created: number; ports: Array<{ id: string; code: string }> }>(
      `/api/assets/${assetId}/ports/ensure`,
      { method: 'POST' },
    ),

  passportUrl: (assetId: string) =>
    apiRequest<{ url: string; kind: string }>('/api/reports/token', {
      method: 'POST',
      body: JSON.stringify({ kind: 'passport', asset_id: assetId }),
    }),

generatePoles: (payload: {
    type_code?: string
    x1: number
    y1: number
    x2: number
    y2: number
    count: number
    start: number
    step: number
    prefix: string
    source_asset_id?: string
    target_asset_id?: string
    path?: number[][]
  }) => apiRequest<{ count: number; first: string; last: string; ids: string[] }>('/api/schema/poles/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),

  renumberPoles: (payload: { type_code?: string; start: number; step: number; prefix: string }) =>
    apiRequest<{ count: number; first: string; last: string }>('/api/schema/poles/renumber', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

renumberPolesChain: (payload: { anchor_asset_id?: string; link_id?: string; type_code?: string; start: number; step: number; prefix: string }) =>
    apiRequest<{ count: number; first: string; last: string }>('/api/schema/poles/renumber-chain', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

placeComposite: (payload: { type_id: string; x: number; y: number; name?: string }) =>
    apiRequest<{ id: string; name: string; code: string; children: number }>('/api/composites/place', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  attachComposite: (parentId: string, childIds: string[]) =>
    apiRequest<{ id: string; name: string; code: string; children: number }>(`/api/composites/${parentId}/attach`, {
      method: 'POST',
      body: JSON.stringify({ child_ids: childIds }),
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

  addBlockCell: (
    assetId: string,
    label: string,
    role = 'outgoing',
    opts: { type_code?: string; x?: number; y?: number } = {},
  ) =>
    apiRequest<{ id: string; code: string; name: string; role: string }>(
      `/api/schema/assets/${assetId}/cells`,
      { method: 'POST', body: JSON.stringify({ label, role, ...opts }) },
    ),

  // --- визуальная сборка схемы: контур, постановка из реестра --------------

  createContour: (payload: {
    name: string
    type_code: string
    x: number
    y: number
    width?: number
    height?: number
    comment?: string
  }) =>
    apiRequest<{ id: string; code: string; name: string; type_code: string; x: number; y: number; width: number; height: number }>(
      '/api/schema/contours',
      { method: 'POST', body: JSON.stringify(payload) },
    ),

  placeOnSchema: (id: string, x: number, y: number) =>
    apiRequest<AssetOut>(`/api/schema/assets/${id}/place`, {
      method: 'POST',
      body: JSON.stringify({ x, y }),
    }),

  /** Атомарно перенести объект/ячейку в другой блок/контур (или на схему). */
  relocateAsset: (assetId: string, payload: RelocateSchemaAssetIn) =>
    apiRequest<RelocateSchemaAssetOut>(`/api/schema/assets/${assetId}/relocate`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  addBlockCellsBulk: (
    assetId: string,
    payload: {
      count: number
      start?: number
      prefix?: string
      suffix?: string
      section_size?: number
      section_prefix?: string
      role?: string
      type_code?: string
    },
  ) =>
    apiRequest<{ parent_id: string; count: number; sections: string[]; items: Array<{ id: string; code: string; name: string; role: string }> }>(
      `/api/schema/assets/${assetId}/cells/bulk`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),

  createCellCable: (
    assetId: string,
    payload: { to_asset_id: string; cable_mark?: string; length_m?: number; cross_section_mm2?: number; cores?: number; link_type?: string },
  ) =>
    apiRequest<LinkOut>(`/api/schema/assets/${assetId}/cables`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  createLineChain: (payload: {
    from_asset_id: string
    to_asset_id: string
    poles: number
    prefix?: string
    link_type?: 'overhead' | 'cable'
    cable_mark?: string
    line_name?: string
    line_code?: string
  }) =>
    apiRequest<{
      line_id: string
      line_code: string
      line_name: string
      poles: Array<{ id: string; code: string; name: string }>
      link_ids: string[]
    }>('/api/schema/lines/chain', { method: 'POST', body: JSON.stringify(payload) }),
  addLineEquipment: (payload: { anchor_asset_id: string; type_code: string; name?: string; cable_mark?: string; link_type?: string }) =>
    apiRequest<{ asset_id: string; code: string; name: string; type_code: string; link_id: string | null; schema_x: number | null; schema_y: number | null }>(
      '/api/schema/line-equipment',
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  unplaceFromSchema: (id: string) =>
    apiRequest<AssetOut>(`/api/schema/assets/${id}/place`, { method: 'DELETE' }),

  // --- снимки схемы (Q-6): черновик, список, публикация ---------------------

  snapshots: (status?: SnapshotStatus) =>
    apiRequest<{ items: SnapshotBrief[]; total: number; published_id: string | null }>(
      `/api/topology/snapshots${status ? `?status=${status}` : ''}`,
    ),

  createSnapshot: (payload: { title: string; comment?: string }) =>
    apiRequest<SnapshotDetail>('/api/topology/snapshots', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  snapshot: (id: string) => apiRequest<SnapshotDetail>(`/api/topology/snapshots/${id}`),

  publishSnapshot: (id: string) =>
    apiRequest<SnapshotDetail>(`/api/topology/snapshots/${id}/publish`, { method: 'POST' }),

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

// Цветовая схема питания (требование заказчика): под напряжением — красный,
// отключено/без питания — зелёный. Отдельно от STATUS_COLOR, который описывает
// эксплуатационный статус для карточек и списков.
export const POWER_COLOR = {
  on: '#F04438',
  off: '#22C55E',
} as const

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

// --- снимки схемы (Q-6) -----------------------------------------------------

export type SnapshotStatus = 'draft' | 'published'

export interface SnapshotCounts {
  nodes: number
  edges: number
  blocks: number
}

export interface SnapshotBrief {
  id: string
  title: string
  comment: string | null
  status: SnapshotStatus
  created_at: string
  created_by: string | null
  created_by_name: string | null
  published_at: string | null
  published_by: string | null
  published_by_name: string | null
  counts: SnapshotCounts
}

export interface SnapshotPayload {
  schema_version: number
  captured_at: string
  pit: { id: string; code: string; name: string; crs_name: string }
  frame: Record<string, unknown>
  graph: TopologyGraph
  counts: SnapshotCounts
}

export interface SnapshotDetail extends SnapshotBrief {
  payload: SnapshotPayload
}