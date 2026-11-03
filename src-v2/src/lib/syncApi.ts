/** Клиент синхронизации: push/pull, конфликты, перемещения. */

import { apiRequest } from './api'

export interface SyncOpResult {
  op_id: string
  status: 'applied' | 'conflict_won' | 'conflict_lost' | 'duplicate' | 'rejected'
  version: number | null
  conflict_id: string | null
  message: string | null
}

export interface ChangeItem {
  seq: number
  entity: string
  entity_id: string
  op: string
  payload: Record<string, unknown>
  actor_id: string | null
  client_ts: string | null
  server_ts: string
}

export interface ConflictItem {
  id: string
  entity: string
  entity_id: string
  kind: string
  winner: string
  winner_payload: Record<string, unknown>
  loser_payload: Record<string, unknown>
  client_ts: string | null
  server_ts: string | null
  note: string | null
  actor_name: string | null
  created_at: string
}

export interface MoveItem {
  id: string
  asset_id: string
  from_x: number | null
  from_y: number | null
  to_x: number
  to_y: number
  moved_at: string
  moved_by_name: string | null
  note: string | null
  source: string
  conflict: boolean
}

export const syncApi = {
  push: (deviceId: string, ops: Array<Record<string, unknown>>) =>
    apiRequest<{ results: SyncOpResult[]; server_seq: number }>('/api/sync/push', {
      method: 'POST',
      body: JSON.stringify({ device_id: deviceId, ops }),
    }),

  pull: (since: number, limit = 200) =>
    apiRequest<{ changes: ChangeItem[]; last_seq: number; has_more: boolean }>(
      `/api/sync/pull?since=${since}&limit=${limit}`,
    ),

  conflicts: () => apiRequest<{ items: ConflictItem[]; total: number }>('/api/sync/conflicts'),

  state: () => apiRequest<{ last_seq: number; conflicts: number; pit_id: string }>('/api/sync/state'),

  move: (
    assetId: string,
    payload: { x: number; y: number; note?: string; media_id?: string; client_ts?: string; source?: string },
  ) => apiRequest<MoveItem>(`/api/assets/${assetId}/move`, { method: 'POST', body: JSON.stringify(payload) }),

  moves: (assetId: string) =>
    apiRequest<{ items: MoveItem[]; total: number }>(`/api/assets/${assetId}/moves`),
}

const DEVICE_KEY = 'karier-device-id'

export function deviceId(): string {
  let value = localStorage.getItem(DEVICE_KEY)
  if (!value) {
    value = `web-${crypto.randomUUID().slice(0, 8)}`
    localStorage.setItem(DEVICE_KEY, value)
  }
  return value
}
