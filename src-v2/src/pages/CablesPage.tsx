import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiError } from '../lib/api'
import type { LinkOut } from '../lib/gis'
import { gisApi } from '../lib/gis'
import { Alert, Badge, PageTitle } from '../components/ui'

const STATUS_LABEL: Record<string, string> = {
  in_work: 'в работе',
  reserve: 'резерв',
  repair: 'ремонт',
  dismounted: 'демонтирован',
}

const TYPE_LABEL: Record<string, string> = {
  cable: 'кабель',
  overhead: 'ВЛ',
  busbar: 'шина',
  jumper: 'перемычка',
  internal: 'внутренняя',
}

export function CablesPage() {
  const [items, setItems] = useState<LinkOut[]>([])
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [editing, setEditing] = useState<LinkOut | null>(null)
  const [form, setForm] = useState({ mark: '', no: '', status: 'in_work', length: '', installed: '', route: '' })
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await gisApi.links({})
      setItems(data.items)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить кабельный журнал')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const rows = useMemo(() => {
    let result = items
    if (statusFilter) result = result.filter((item) => item.cable_status === statusFilter)
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      result = result.filter(
        (item) =>
          (item.cable_no ?? '').toLowerCase().includes(q) ||
          (item.cable_mark ?? '').toLowerCase().includes(q) ||
          item.from_asset.name.toLowerCase().includes(q) ||
          item.to_asset.name.toLowerCase().includes(q),
      )
    }
    return result
  }, [items, search, statusFilter])

  const openEditor = (link: LinkOut) => {
    setEditing(link)
    setForm({
      mark: link.cable_mark ?? '',
      no: link.cable_no ?? '',
      status: link.cable_status ?? 'in_work',
      length: link.length_m != null ? String(link.length_m) : '',
      installed: link.installed_on ?? '',
      route: link.route_note ?? '',
    })
  }

  const save = async () => {
    if (!editing) return
    setBusy(true)
    try {
      await gisApi.updateLink(editing.id, {
        cable_mark: form.mark || null,
        cable_no: form.no || null,
        cable_status: form.status,
        length_m: form.length ? Number(form.length) : null,
        installed_on: form.installed || null,
        route_note: form.route || null,
      })
      setEditing(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить кабель')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <PageTitle
        title="Кабельный журнал"
        subtitle="Номера кабелей, марки, длины, статус (в работе/резерв/ремонт) и место установки"
      />

      {error ? <Alert kind="error">{error}</Alert> : null}

      <div className="card flex flex-wrap items-end gap-2">
        <label className="min-w-[220px] flex-1">
          <span className="label">Поиск</span>
          <input className="input h-10" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="номер, марка, объект" />
        </label>
        <label>
          <span className="label">Статус</span>
          <select className="input h-10" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">все</option>
            {Object.entries(STATUS_LABEL).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <span className="ml-auto text-[12px] text-ink3">Показано {rows.length} из {items.length}</span>
      </div>

      <div className="space-y-2 md:hidden">
        {rows.map((link) => (
          <button key={link.id} type="button" className="card w-full p-3 text-left" onClick={() => openEditor(link)}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[12px] text-ink3">{link.cable_no ?? '—'}</span>
              <Badge tone={link.cable_status === 'repair' ? 'bad' : link.cable_status === 'reserve' ? 'warm' : 'ok'}>
                {STATUS_LABEL[link.cable_status ?? 'in_work']}
              </Badge>
            </div>
            <div className="mt-1 text-[14px]">{link.cable_mark ?? 'без марки'}</div>
            <div className="text-[12px] text-ink3">
              {link.from_asset.name} → {link.to_asset.name}
            </div>
            <div className="text-[12px] text-ink3">
              {TYPE_LABEL[link.link_type] ?? link.link_type} · {link.length_m ?? '—'} м
            </div>
          </button>
        ))}
      </div>

      <div className="card hidden overflow-x-auto md:block">
        <table className="w-full text-[13px]">
          <thead className="text-left text-[11px] uppercase text-ink3">
            <tr>
              <th className="px-3 py-2">№ кабеля</th>
              <th className="px-3 py-2">Марка</th>
              <th className="px-3 py-2">Тип</th>
              <th className="px-3 py-2">Статус</th>
              <th className="px-3 py-2">Длина</th>
              <th className="px-3 py-2">Откуда → куда</th>
              <th className="px-3 py-2">Установлен на</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((link) => (
              <tr key={link.id} className="cursor-pointer hover:bg-surface2/40" onClick={() => openEditor(link)}>
                <td className="px-3 py-2 font-mono">{link.cable_no ?? '—'}</td>
                <td className="px-3 py-2">{link.cable_mark ?? '—'}</td>
                <td className="px-3 py-2">{TYPE_LABEL[link.link_type] ?? link.link_type}</td>
                <td className="px-3 py-2">{STATUS_LABEL[link.cable_status ?? 'in_work']}</td>
                <td className="px-3 py-2">{link.length_m ?? '—'} м</td>
                <td className="px-3 py-2">{link.from_asset.name} → {link.to_asset.name}</td>
                <td className="px-3 py-2">{link.installed_on ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing ? (
        <div className="fixed inset-0 z-[1400] flex items-end justify-center bg-black/60 p-3 sm:items-center">
          <div className="card modal-safe w-full max-w-md p-4">
            <div className="mb-3 text-[15px] font-semibold">Кабель</div>
            <div className="mb-2 grid grid-cols-2 gap-2">
              <label className="text-[11px] text-ink3">
                Номер
                <input className="input mt-1 h-9" value={form.no} onChange={(e) => setForm({ ...form, no: e.target.value })} placeholder="КЛ-17" />
              </label>
              <label className="text-[11px] text-ink3">
                Марка
                <input className="input mt-1 h-9" value={form.mark} onChange={(e) => setForm({ ...form, mark: e.target.value })} placeholder="СБ-3×95" />
              </label>
              <label className="text-[11px] text-ink3">
                Статус
                <select className="input mt-1 h-9" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {Object.entries(STATUS_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </label>
              <label className="text-[11px] text-ink3">
                Длина, м
                <input className="input mt-1 h-9" inputMode="decimal" value={form.length} onChange={(e) => setForm({ ...form, length: e.target.value })} />
              </label>
            </div>
            <label className="mb-2 block text-[11px] text-ink3">
              Установлен на
              <input className="input mt-1 h-9" value={form.installed} onChange={(e) => setForm({ ...form, installed: e.target.value })} placeholder="оп.4 / КТП №4" />
            </label>
            <label className="mb-3 block text-[11px] text-ink3">
              Примечание
              <input className="input mt-1 h-9" value={form.route} onChange={(e) => setForm({ ...form, route: e.target.value })} placeholder="вдоль дороги" />
            </label>
            <div className="flex gap-2">
              <button type="button" className="btn-primary h-9 flex-1" disabled={busy} onClick={() => void save()}>Сохранить</button>
              <button type="button" className="btn-ghost h-9" onClick={() => setEditing(null)}>Отмена</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
