/** Клиент дашборда и выгрузок. */

import { apiRequest } from './api'

export interface DashboardSummary {
  generated_at: string
  assets: {
    total: number
    energized: number
    deenergized: number
    grounded: number
    by_status: Record<string, number>
    by_type: Record<string, number>
  }
  defects: {
    open: number
    by_severity: Record<string, number>
    by_category: Record<string, number>
    fixed_last_week: number
  }
  inspections: {
    week: number
    week_defects: number
    checked_items: number
    total: number
  }
  mobile: Array<{
    id: string
    code: string
    name: string
    status: string
    x: number | null
    y: number | null
    moved_at: string | null
    days_since_move: number | null
    last_note: string | null
  }>
}

export const dashboardApi = {
  summary: () => apiRequest<DashboardSummary>('/api/dashboard/summary'),

  exportLink: (kind: 'assets' | 'defects' | 'switching' | 'inspections' | 'passport', assetId?: string) =>
    apiRequest<{ url: string; kind: string }>('/api/reports/token', {
      method: 'POST',
      body: JSON.stringify({ kind, asset_id: assetId }),
    }),
}

/** Открыть выгрузку в новой вкладке по короткоживущей ссылке. */
export async function openExport(
  kind: 'assets' | 'defects' | 'switching' | 'inspections' | 'passport',
  assetId?: string,
): Promise<void> {
  const { url } = await dashboardApi.exportLink(kind, assetId)
  window.open(url, '_blank', 'noopener')
}
