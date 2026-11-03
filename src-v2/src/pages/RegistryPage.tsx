import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { Alert, Badge, PageTitle } from '../components/ui'
import { ApiError } from '../lib/api'
import type { AssetBrief, AssetType } from '../lib/gis'
import { STATUS_COLOR, STATUS_LABEL, gisApi } from '../lib/gis'
import { openExport } from '../lib/dashboard'

type SortKey = 'code' | 'name' | 'type' | 'status' | 'x' | 'y'

export function RegistryPage() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const [items, setItems] = useState<AssetBrief[]>([])
  const [types, setTypes] = useState<AssetType[]>([])
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [parentFilter, setParentFilter] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'code', dir: 1 })

  const load = useCallback(async () => {
    try {
      const [assetsData, typesData] = await Promise.all([gisApi.assets(), gisApi.types()])
      setItems(assetsData.items)
      setTypes(typesData)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить реестр')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const parents = useMemo(
    () =>
      items
        .filter((item) => ['source', 'equipment'].includes(item.type.category) && item.type.code !== 'cell')
        .sort((a, b) => a.code.localeCompare(b.code)),
    [items],
  )

  const rows = useMemo(() => {
    let result = [...items]
    if (search.trim()) {
      const needle = search.trim().toLowerCase()
      result = result.filter(
        (item) => item.name.toLowerCase().includes(needle) || item.code.toLowerCase().includes(needle),
      )
    }
    if (typeFilter) result = result.filter((item) => item.type.code === typeFilter)
    if (statusFilter) result = result.filter((item) => item.status === statusFilter)
    if (parentFilter) result = result.filter((item) => item.parent_id === parentFilter)

    const value = (item: AssetBrief, key: SortKey): string | number => {
      if (key === 'type') return item.type.name
      if (key === 'x') return item.x ?? -1
      if (key === 'y') return item.y ?? -1
      if (key === 'name') return item.name
      if (key === 'status') return item.status
      return item.code
    }

    result.sort((a, b) => {
      const left = value(a, sort.key)
      const right = value(b, sort.key)
      if (typeof left === 'number' && typeof right === 'number') return (left - right) * sort.dir
      return String(left).localeCompare(String(right), 'ru') * sort.dir
    })
    return result
  }, [items, search, typeFilter, statusFilter, parentFilter, sort])

  const toggleSort = (key: SortKey) => {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === 1 ? -1 : 1 } : { key, dir: 1 }))
  }

  const header = (key: SortKey, label: string) => (
    <th className="whitespace-nowrap px-3 py-2 font-medium">
      <button type="button" className="inline-flex items-center gap-1 hover:text-ink" onClick={() => toggleSort(key)}>
        {label}
        {sort.key === key ? <span className="text-accent">{sort.dir === 1 ? '▲' : '▼'}</span> : null}
      </button>
    </th>
  )

  return (
    <div className="space-y-4">
      <PageTitle
        title="Реестр оборудования"
        subtitle="Все объекты карьера: тип, состояние, родитель, координаты. Админ может разместить объект на карте"
      />

      {error ? <Alert kind="error">{error}</Alert> : null}

      <div className="card flex flex-wrap items-end gap-2">
        <label className="min-w-[220px] flex-1">
          <span className="label">Поиск</span>
          <input
            className="input h-10"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Название или код"
          />
        </label>
        <label>
          <span className="label">Тип</span>
          <select className="input h-10 w-auto" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="">Все</option>
            {types.map((type) => (
              <option key={type.code} value={type.code}>
                {type.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="label">Состояние</span>
          <select className="input h-10 w-auto" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">Все</option>
            {Object.entries(STATUS_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="label">Родитель</span>
          <select className="input h-10 w-auto" value={parentFilter} onChange={(e) => setParentFilter(e.target.value)}>
            <option value="">Все</option>
            {parents.map((item) => (
              <option key={item.id} value={item.id}>
                {item.code}
              </option>
            ))}
          </select>
        </label>
        {can('report.export') ? (
          <button
            type="button"
            className="btn-ghost h-10 px-3 text-[12px]"
            onClick={() => void openExport('assets')}
          >
            ⬇ Excel
          </button>
        ) : null}
        <span className="ml-auto text-[12px] text-ink3">Показано {rows.length} из {items.length}</span>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full min-w-[900px] text-left text-[13px]">
          <thead className="bg-surface2/60 text-[12px] uppercase tracking-wide text-ink3">
            <tr>
              {header('code', 'Код')}
              {header('name', 'Название')}
              {header('type', 'Тип')}
              {header('status', 'Состояние')}
              {header('x', 'X, м')}
              {header('y', 'Y, м')}
              <th className="px-3 py-2 font-medium">Действия</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((item) => (
              <tr key={item.id} className="align-middle">
                <td className="whitespace-nowrap px-3 py-2 font-mono text-[12px]">{item.code}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span>{item.type.icon}</span>
                    <span>{item.name}</span>
                    {item.is_mobile ? <Badge tone="accent">мобильный</Badge> : null}
                  </div>
                </td>
                <td className="px-3 py-2 text-ink2">{item.type.name}</td>
                <td className="whitespace-nowrap px-3 py-2">
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      className="inline-block h-2 w-2 rounded-full"
                      style={{ background: STATUS_COLOR[item.status] }}
                    />
                    {STATUS_LABEL[item.status] ?? item.status}
                  </span>
                  {item.grounded ? <span className="ml-1 text-ground">⏚</span> : null}
                </td>
                <td className="px-3 py-2 font-mono text-[12px] text-ink2">{item.x ?? '—'}</td>
                <td className="px-3 py-2 font-mono text-[12px] text-ink2">{item.y ?? '—'}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      className="btn-ghost h-8 px-2.5 text-[12px]"
                      onClick={() => navigate('/map', { state: { openAssetId: item.id } })}
                    >
                      На карте
                    </button>
                    {can('asset.create') ? (
                      <button
                        type="button"
                        className="btn-ghost h-8 px-2.5 text-[12px]"
                        onClick={() => navigate('/map', { state: { placeAssetId: item.id } })}
                      >
                        {item.x === null ? 'Разместить' : 'Переместить'}
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-ink3">
                  Ничего не найдено
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}
