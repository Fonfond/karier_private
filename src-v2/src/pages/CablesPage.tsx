import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { ApiError } from '../lib/api'
import type { AssetBrief, CableRecord, CableState, LinkOut } from '../lib/gis'
import { POWER_COLOR, gisApi } from '../lib/gis'
import { Alert, Badge, PageTitle } from '../components/ui'

const CABLE_TABS: Array<{ key: CableState; label: string; hint: string }> = [
  { key: 'installed', label: 'На оборудовании', hint: 'кабели, установленные на участках линий и объектах' },
  { key: 'reserve', label: 'В запасе', hint: 'свободные кабели: можно установить на связь или объект' },
  { key: 'repair', label: 'В ремонте', hint: 'кабели в ремонте — из учёта не выбывают' },
]

const CABLE_STATE_LABEL: Record<CableState, string> = {
  installed: 'на оборудовании',
  reserve: 'в запасе',
  repair: 'в ремонте',
}

const CABLE_STATE_TONE: Record<CableState, 'ok' | 'accent' | 'warm'> = {
  installed: 'ok',
  reserve: 'accent',
  repair: 'warm',
}

/** Старый журнал связей (link-поля) — оставлен вкладкой, чтобы не потерять данные. */
const LINK_STATUS_LABEL: Record<string, string> = {
  in_work: 'в работе',
  reserve: 'резерв',
  repair: 'ремонт',
  dismounted: 'демонтирован',
}

const LINK_TYPE_LABEL: Record<string, string> = {
  cable: 'кабель',
  overhead: 'ВЛ',
  busbar: 'шина',
  jumper: 'перемычка',
  internal: 'внутренняя',
}

type Tab = CableState | 'journal'

interface InstallTarget {
  kind: 'link' | 'asset'
  id: string
}

export function CablesPage() {
  const { can } = useAuth()
  const canManage = can('asset.status.edit')

  const [tab, setTab] = useState<Tab>('installed')
  const [items, setItems] = useState<CableRecord[]>([])
  const [allCables, setAllCables] = useState<CableRecord[]>([])
  const [links, setLinks] = useState<LinkOut[]>([])
  const [assets, setAssets] = useState<AssetBrief[]>([])
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // установка кабеля: выбор связи или объекта
  const [installFor, setInstallFor] = useState<CableRecord | null>(null)
  const [installTarget, setInstallTarget] = useState<InstallTarget>({ kind: 'link', id: '' })
  const [installReason, setInstallReason] = useState('')
  const [assetQuery, setAssetQuery] = useState('')
  // снятие кабеля: в запас или в ремонт
  const [returnFor, setReturnFor] = useState<CableRecord | null>(null)
  const [returnStatus, setReturnStatus] = useState<CableState>('reserve')
  const [returnReason, setReturnReason] = useState('')

  // журнал связей (legacy)
  const [editingLink, setEditingLink] = useState<LinkOut | null>(null)
  const [linkForm, setLinkForm] = useState({ mark: '', no: '', status: 'in_work', length: '', installed: '', route: '' })

  const activeState: CableState | null = tab === 'journal' ? null : tab

  // Ответы приходят в произвольном порядке: защищаемся от гонки при быстром
  // переключении вкладок (иначе список «в запасе» перезапишет ответ «на оборудовании»).
  const requestSeq = useRef(0)
  const [loading, setLoading] = useState(false)
  const [targetsLoading, setTargetsLoading] = useState(false)

  const load = useCallback(async () => {
    const seq = requestSeq.current + 1
    requestSeq.current = seq
    setLoading(true)
    try {
      const [current, all] = await Promise.all([
        activeState
          ? gisApi.cables({ lifecycle_status: activeState })
          : gisApi.cables({}),
        gisApi.cables({}).catch(() => [] as CableRecord[]),
      ])
      if (seq !== requestSeq.current) return
      setItems(current)
      setAllCables(all)
      setError(null)
    } catch (err) {
      if (seq !== requestSeq.current) return
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить кабельный учёт')
    } finally {
      if (seq === requestSeq.current) setLoading(false)
    }
  }, [activeState])

  /**
   * Справочники для установки (свободные связи и объекты) грузим по требованию:
   * 500 объектов и 3800 связей нужны только в диалоге, а не на каждой вкладке.
   */
  const ensureTargets = useCallback(async () => {
    if (links.length > 0 && assets.length > 0) return
    setTargetsLoading(true)
    try {
      const [linkList, assetList] = await Promise.all([
        gisApi.links({}).then((data) => data.items).catch(() => [] as LinkOut[]),
        gisApi.assets().then((data) => data.items).catch(() => [] as AssetBrief[]),
      ])
      setLinks(linkList)
      setAssets(assetList)
    } finally {
      setTargetsLoading(false)
    }
  }, [links.length, assets.length])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (installFor || tab === 'journal') void ensureTargets()
  }, [installFor, tab, ensureTargets])

  const counts = useMemo(() => {
    const result: Record<CableState, number> = { installed: 0, reserve: 0, repair: 0 }
    for (const cable of allCables) {
      const state = cable.lifecycle_status ?? 'installed'
      if (state in result) result[state as CableState] += 1
    }
    return result
  }, [allCables])

  /** Связи, на которые можно поставить кабель: без кабеля, кабельные/воздушные. */
  const freeLinks = useMemo(
    () =>
      links.filter(
        (link) =>
          (link.link_type === 'cable' || link.link_type === 'overhead') &&
          !link.cable_asset_id &&
          link.cable_status !== 'dismounted',
      ),
    [links],
  )

  /** Объекты для установки кабеля (кроме самих кабелей), с поиском. */
  const assetOptions = useMemo(() => {
    const query = assetQuery.trim().toLowerCase()
    const pool = assets.filter((item) => item.type.equipment_class !== 'cable')
    const matched = query
      ? pool.filter(
          (item) =>
            item.name.toLowerCase().includes(query) || item.code.toLowerCase().includes(query),
        )
      : pool
    return matched.slice(0, 30)
  }, [assets, assetQuery])

  const selectedAsset = assets.find((item) => item.id === installTarget.id) ?? null

  const rows = useMemo(() => {    const query = search.trim().toLowerCase()
    if (!query) return items
    return items.filter(
      (cable) =>
        cable.code.toLowerCase().includes(query) ||
        cable.name.toLowerCase().includes(query) ||
        (cable.cable_mark ?? '').toLowerCase().includes(query) ||
        (cable.link_label ?? '').toLowerCase().includes(query) ||
        (cable.installed_on ?? '').toLowerCase().includes(query),
    )
  }, [items, search])

  const journalRows = useMemo(() => {
    const query = search.trim().toLowerCase()
    const base = links.filter((link) => link.link_type === 'cable' || link.link_type === 'overhead')
    if (!query) return base
    return base.filter(
      (link) =>
        (link.cable_no ?? '').toLowerCase().includes(query) ||
        (link.cable_mark ?? '').toLowerCase().includes(query) ||
        link.from_asset.name.toLowerCase().includes(query) ||
        link.to_asset.name.toLowerCase().includes(query),
    )
  }, [links, search])

  const openInstall = (cable: CableRecord) => {
    setInstallFor(cable)
    setInstallReason('')
    const firstLink = freeLinks[0]
    setInstallTarget(firstLink ? { kind: 'link', id: firstLink.id } : { kind: 'link', id: '' })
  }

  // Свободные связи приходят позже диалога — подставляем первую, когда загрузились.
  useEffect(() => {
    if (!installFor) return
    if (installTarget.id) return
    const firstLink = freeLinks[0]
    if (firstLink) setInstallTarget({ kind: 'link', id: firstLink.id })
  }, [installFor, installTarget.id, freeLinks])

  const submitInstall = async () => {
    if (!installFor) return
    if (!installTarget.id) {
      setError('Выберите участок связи или объект, куда поставить кабель')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const payload =
        installTarget.kind === 'link'
          ? { link_id: installTarget.id, reason: installReason.trim() || undefined }
          : { asset_id: installTarget.id, reason: installReason.trim() || undefined }
      const result = await gisApi.installCable(installFor.id, payload)
      setNotice(
        `Кабель «${result.cable.name}» установлен: ${
          result.link_label ?? result.cable.installed_on ?? 'объект'
        }`,
      )
      setInstallFor(null)
      await load()
    } catch (err) {
      if (err instanceof ApiError) {
        const hints: Record<string, string> = {
          'cable.already_installed': 'Кабель уже установлен — сначала снимите его',
          'cable.link_occupied': 'На этом участке уже стоит другой кабель',
          'cable.link_ambiguous': 'У объекта несколько свободных связей — выберите участок связи',
          'cable.not_cable': 'Объект не является кабелем',
        }
        setError(hints[err.code] ?? err.message)
      } else {
        setError('Не удалось установить кабель')
      }
    } finally {
      setBusy(false)
    }
  }

  const openReturn = (cable: CableRecord) => {
    setReturnFor(cable)
    setReturnStatus('reserve')
    setReturnReason('')
  }

  const submitReturn = async () => {
    if (!returnFor) return
    setBusy(true)
    setError(null)
    try {
      const result = await gisApi.returnCable(returnFor.id, {
        status: returnStatus,
        reason: returnReason.trim() || undefined,
      })
      const detached = result.detached_links.length
      setNotice(
        `Кабель «${result.cable.name}» снят — ${CABLE_STATE_LABEL[result.cable.lifecycle_status]}` +
          (detached > 0 ? `; освобождено связей: ${detached}` : ''),
      )
      setReturnFor(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось снять кабель')
    } finally {
      setBusy(false)
    }
  }

  const openLinkEditor = (link: LinkOut) => {
    setEditingLink(link)
    setLinkForm({
      mark: link.cable_mark ?? '',
      no: link.cable_no ?? '',
      status: link.cable_status ?? 'in_work',
      length: link.length_m != null ? String(link.length_m) : '',
      installed: link.installed_on ?? '',
      route: link.route_note ?? '',
    })
  }

  const saveLink = async () => {
    if (!editingLink) return
    setBusy(true)
    try {
      await gisApi.updateLink(editingLink.id, {
        cable_mark: linkForm.mark || null,
        cable_no: linkForm.no || null,
        cable_status: linkForm.status,
        length_m: linkForm.length ? Number(linkForm.length) : null,
        installed_on: linkForm.installed || null,
        route_note: linkForm.route || null,
      })
      setEditingLink(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить кабель')
    } finally {
      setBusy(false)
    }
  }

  const bindingText = (cable: CableRecord) => {
    if (cable.link_label && cable.from_asset && cable.to_asset) {
      return `${cable.link_label} · ${cable.from_asset.name} → ${cable.to_asset.name}`
    }
    return cable.link_label ?? cable.installed_on ?? 'не установлен'
  }

  return (
    <div className="space-y-3">
      <PageTitle
        title="Кабельный учёт"
        subtitle="Кабели как объекты реестра: на оборудовании (installed), в запасе (reserve), в ремонте (repair). Установка и снятие фиксируются в аудите."
      />

      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-line bg-surface2/40 p-1">
        {CABLE_TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            data-testid={`cables-tab-${item.key}`}
            aria-pressed={tab === item.key}
            className={`rounded-lg px-3 py-2 text-[12px] ${
              tab === item.key ? 'bg-accent text-[#08131F]' : 'text-ink2 hover:bg-surface2'
            }`}
            onClick={() => {
              setTab(item.key)
              setNotice(null)
            }}
          >
            {item.label}
            <span className={tab === item.key ? 'ml-1.5 opacity-80' : 'ml-1.5 text-ink3'}>{counts[item.key]}</span>
          </button>
        ))}
        <button
          type="button"
          aria-pressed={tab === 'journal'}
          className={`ml-auto rounded-lg px-3 py-2 text-[11px] ${
            tab === 'journal' ? 'bg-accent text-[#08131F]' : 'text-ink3 hover:bg-surface2'
          }`}
          onClick={() => setTab('journal')}
        >
          Журнал связей
        </button>
      </div>

      <div className="card flex flex-wrap items-end gap-2">
        <label className="min-w-[220px] flex-1">
          <span className="label">Поиск</span>
          <input
            className="input h-10"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="код, марка, объект, участок"
          />
        </label>
        <span className="ml-auto text-[12px] text-ink3">
          {tab === 'journal'
            ? `связей: ${journalRows.length}`
            : loading
              ? 'загружаем кабели…'
              : `показано ${rows.length} из ${items.length} · ${
                  CABLE_TABS.find((item) => item.key === tab)?.hint ?? ''
                }`}
        </span>
      </div>

      {tab === 'journal' ? (
        <>
          <div className="space-y-2 md:hidden">
            {journalRows.map((link) => (
              <button key={link.id} type="button" className="card w-full p-3 text-left" onClick={() => openLinkEditor(link)}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[12px] text-ink3">{link.cable_no ?? '—'}</span>
                  <Badge tone={link.cable_status === 'repair' ? 'bad' : link.cable_status === 'reserve' ? 'warm' : 'ok'}>
                    {LINK_STATUS_LABEL[link.cable_status ?? 'in_work']}
                  </Badge>
                </div>
                <div className="mt-1 text-[14px]">{link.cable_mark ?? 'без марки'}</div>
                <div className="text-[12px] text-ink3">
                  {link.from_asset.name} → {link.to_asset.name}
                </div>
                <div className="text-[12px] text-ink3">
                  {LINK_TYPE_LABEL[link.link_type] ?? link.link_type} · {link.length_m ?? '—'} м
                </div>
                {link.cable_asset ? (
                  <div className="mt-1 text-[11px] text-accent">кабель-объект: {link.cable_asset.name}</div>
                ) : null}
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
                  <th className="px-3 py-2">Кабель-объект</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {journalRows.map((link) => (
                  <tr key={link.id} className="cursor-pointer hover:bg-surface2/40" onClick={() => openLinkEditor(link)}>
                    <td className="px-3 py-2 font-mono">{link.cable_no ?? '—'}</td>
                    <td className="px-3 py-2">{link.cable_mark ?? '—'}</td>
                    <td className="px-3 py-2">{LINK_TYPE_LABEL[link.link_type] ?? link.link_type}</td>
                    <td className="px-3 py-2">{LINK_STATUS_LABEL[link.cable_status ?? 'in_work']}</td>
                    <td className="px-3 py-2">{link.length_m ?? '—'} м</td>
                    <td className="px-3 py-2">
                      {link.from_asset.name} → {link.to_asset.name}
                    </td>
                    <td className="px-3 py-2">{link.installed_on ?? '—'}</td>
                    <td className="px-3 py-2">
                      {link.cable_asset ? (
                        <span className="text-accent">{link.cable_asset.name}</span>
                      ) : (
                        <span className="text-ink3">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <>
          <div className="space-y-2 md:hidden">
            {rows.map((cable) => (
              <div key={cable.id} className="card p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-mono text-[11px] text-ink3">{cable.code}</div>
                    <div className="truncate text-[14px] font-medium">{cable.name}</div>
                    <div className="text-[11px] text-ink3">
                      {cable.cable_mark ?? 'без марки'} · {cable.section_mm2 ?? '—'} мм² · {cable.length_m ?? '—'} м
                    </div>
                  </div>
                  <Badge tone={CABLE_STATE_TONE[cable.lifecycle_status] ?? 'neutral'}>
                    {CABLE_STATE_LABEL[cable.lifecycle_status] ?? cable.lifecycle_status}
                  </Badge>
                </div>
                <div className="mt-1 text-[12px] text-ink2">Привязка: {bindingText(cable)}</div>
                {canManage ? (
                  <div className="mt-2 flex gap-2">
                    {cable.lifecycle_status === 'installed' ? (
                      <button type="button" className="btn-ghost h-9 flex-1 text-[12px]" onClick={() => openReturn(cable)}>
                        Снять
                      </button>
                    ) : (
                      <button type="button" className="btn-primary h-9 flex-1 text-[12px]" onClick={() => openInstall(cable)}>
                        Установить
                      </button>
                    )}
                  </div>
                ) : null}
              </div>
            ))}
            {rows.length === 0 ? <div className="card text-[13px] text-ink3">В этой вкладке кабелей нет</div> : null}
          </div>

          <div className="card hidden overflow-x-auto md:block">
            <table className="w-full min-w-[860px] text-[13px]">
              <thead className="text-left text-[11px] uppercase text-ink3">
                <tr>
                  <th className="px-3 py-2">Код</th>
                  <th className="px-3 py-2">Кабель</th>
                  <th className="px-3 py-2">Марка · сечение</th>
                  <th className="px-3 py-2">Длина</th>
                  <th className="px-3 py-2">Статус</th>
                  <th className="px-3 py-2">Привязка</th>
                  <th className="px-3 py-2">Действия</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((cable) => (
                  <tr key={cable.id}>
                    <td className="px-3 py-2 font-mono text-[12px]">{cable.code}</td>
                    <td className="px-3 py-2">{cable.name}</td>
                    <td className="px-3 py-2">
                      {cable.cable_mark ?? '—'} · {cable.section_mm2 ?? '—'} мм²
                    </td>
                    <td className="px-3 py-2">{cable.length_m ?? '—'} м</td>
                    <td className="px-3 py-2">
                      <Badge tone={CABLE_STATE_TONE[cable.lifecycle_status] ?? 'neutral'}>
                        {CABLE_STATE_LABEL[cable.lifecycle_status] ?? cable.lifecycle_status}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-[12px] text-ink2">{bindingText(cable)}</td>
                    <td className="px-3 py-2">
                      {canManage ? (
                        cable.lifecycle_status === 'installed' ? (
                          <button type="button" className="btn-ghost h-8 px-2.5 text-[12px]" onClick={() => openReturn(cable)}>
                            Снять
                          </button>
                        ) : (
                          <button type="button" className="btn-primary h-8 px-2.5 text-[12px]" onClick={() => openInstall(cable)}>
                            Установить
                          </button>
                        )
                      ) : (
                        <span className="text-[11px] text-ink3">только просмотр</span>
                      )}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-3 py-8 text-center text-ink3">
                      В этой вкладке кабелей нет
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Установка кабеля: участок связи или объект */}
      {installFor ? (
        <div className="fixed inset-0 z-[1400] flex items-end justify-center bg-black/60 p-3 sm:items-center">
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Установить кабель"
            className="card modal-safe w-full max-w-md p-4 text-[13px]"
          >
            <div className="mb-1 text-[15px] font-semibold">Установить кабель</div>
            <p className="mb-2 text-[12px] text-ink3">
              {installFor.name} · {installFor.cable_mark ?? 'без марки'} · {installFor.length_m ?? '—'} м
            </p>
            {targetsLoading ? (
              <div className="mb-2 text-[11px] text-ink3">Загружаем свободные связи и объекты…</div>
            ) : null}
            <div className="mb-2 space-y-1">
              <label className="flex items-center gap-2 text-[12px] text-ink2">
                <input
                  type="radio"
                  checked={installTarget.kind === 'link'}
                  onChange={() =>
                    setInstallTarget({ kind: 'link', id: freeLinks[0]?.id ?? '' })
                  }
                />
                на участок связи (свободных: {freeLinks.length})
              </label>
              <label className="flex items-center gap-2 text-[12px] text-ink2">
                <input
                  type="radio"
                  checked={installTarget.kind === 'asset'}
                  onChange={() => setInstallTarget({ kind: 'asset', id: '' })}
                />
                на объект (без участка)
              </label>
            </div>
            {installTarget.kind === 'link' ? (
              <label className="mb-2 block text-[11px] text-ink3">
                Участок связи
                <select
                  className="input mt-1 h-9"
                  value={installTarget.id}
                  onChange={(event) => setInstallTarget({ kind: 'link', id: event.target.value })}
                >
                  <option value="">— выберите —</option>
                  {freeLinks.map((link) => (
                    <option key={link.id} value={link.id}>
                      {link.label} · {link.from_asset.name} → {link.to_asset.name}
                    </option>
                  ))}
                </select>
                {freeLinks.length === 0 ? (
                  <span className="mt-1 block text-[11px] text-warm">
                    Свободных связей нет — создайте связь в редакторе схемы или поставьте кабель на объект.
                  </span>
                ) : null}
              </label>
            ) : (
              <div className="mb-2">
                <label className="block text-[11px] text-ink3">
                  Объект: поиск по коду или названию
                  <input
                    className="input mt-1 h-9"
                    value={assetQuery}
                    onChange={(event) => setAssetQuery(event.target.value)}
                    placeholder="ячейка, опора, КТП"
                  />
                </label>
                {selectedAsset ? (
                  <div className="mt-1 rounded-lg border border-accent/40 bg-accent/10 px-2 py-1 text-[11px] text-accent">
                    Выбрано: {selectedAsset.code} · {selectedAsset.name}
                  </div>
                ) : null}
                <div className="mt-1 max-h-36 overflow-y-auto rounded-lg border border-line">
                  {assetOptions.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className={`flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left text-[12px] hover:bg-surface2 ${
                        installTarget.id === item.id ? 'bg-accent/15' : ''
                      }`}
                      onClick={() => setInstallTarget({ kind: 'asset', id: item.id })}
                    >
                      <span className="truncate">{item.name}</span>
                      <span className="shrink-0 text-[10px] text-ink3">{item.code}</span>
                    </button>
                  ))}
                  {assetOptions.length === 0 ? (
                    <p className="px-2 py-2 text-[11px] text-ink3">Ничего не найдено</p>
                  ) : null}
                </div>
                <span className="mt-1 block text-[11px] text-ink3">
                  Если у объекта ровно одна свободная кабельная связь — кабель встанет на неё.
                </span>
              </div>
            )}
            <label className="mb-3 block text-[11px] text-ink3">
              Причина / примечание
              <input
                className="input mt-1 h-9"
                value={installReason}
                onChange={(event) => setInstallReason(event.target.value)}
                placeholder="например, монтаж ф.7К"
              />
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn-primary h-9 flex-1"
                data-testid="cable-install-submit"
                disabled={busy || targetsLoading || !installTarget.id}
                onClick={() => void submitInstall()}
              >
                {busy ? 'Устанавливаем…' : 'Установить'}
              </button>
              <button type="button" className="btn-ghost h-9" onClick={() => setInstallFor(null)}>
                Отмена
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Снятие кабеля: в запас или в ремонт */}
      {returnFor ? (
        <div className="fixed inset-0 z-[1400] flex items-end justify-center bg-black/60 p-3 sm:items-center">
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Снять кабель"
            className="card modal-safe w-full max-w-md p-4 text-[13px]"
          >
            <div className="mb-1 text-[15px] font-semibold">Снять кабель</div>
            <p className="mb-2 text-[12px] text-ink3">
              {returnFor.name} · привязка: {bindingText(returnFor)}
            </p>
            <label className="mb-2 block text-[11px] text-ink3">
              Куда снять
              <select
                className="input mt-1 h-9"
                value={returnStatus}
                onChange={(event) => setReturnStatus(event.target.value as CableState)}
              >
                <option value="reserve">в запас</option>
                <option value="repair">в ремонт</option>
                <option value="installed">оставить установленным</option>
              </select>
            </label>
            <label className="mb-3 block text-[11px] text-ink3">
              Причина
              <input
                className="input mt-1 h-9"
                value={returnReason}
                onChange={(event) => setReturnReason(event.target.value)}
                placeholder="например, плановый демонтаж"
              />
            </label>
            <div className="flex gap-2">
              <button
                type="button"
                className="btn-primary h-9 flex-1"
                data-testid="cable-return-submit"
                disabled={busy}
                onClick={() => void submitReturn()}
              >
                {busy ? 'Снимаем…' : 'Снять'}
              </button>
              <button type="button" className="btn-ghost h-9" onClick={() => setReturnFor(null)}>
                Отмена
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Журнал связей: старая форма (link-поля) */}
      {editingLink ? (
        <div className="fixed inset-0 z-[1400] flex items-end justify-center bg-black/60 p-3 sm:items-center">
          <div className="card modal-safe w-full max-w-md p-4">
            <div className="mb-3 text-[15px] font-semibold">Связь · кабель</div>
            <div className="mb-2 grid grid-cols-2 gap-2">
              <label className="text-[11px] text-ink3">
                Номер
                <input className="input mt-1 h-9" value={linkForm.no} onChange={(event) => setLinkForm({ ...linkForm, no: event.target.value })} placeholder="КЛ-17" />
              </label>
              <label className="text-[11px] text-ink3">
                Марка
                <input className="input mt-1 h-9" value={linkForm.mark} onChange={(event) => setLinkForm({ ...linkForm, mark: event.target.value })} placeholder="СБ-3×95" />
              </label>
              <label className="text-[11px] text-ink3">
                Статус
                <select className="input mt-1 h-9" value={linkForm.status} onChange={(event) => setLinkForm({ ...linkForm, status: event.target.value })}>
                  {Object.entries(LINK_STATUS_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-[11px] text-ink3">
                Длина, м
                <input className="input mt-1 h-9" inputMode="decimal" value={linkForm.length} onChange={(event) => setLinkForm({ ...linkForm, length: event.target.value })} />
              </label>
            </div>
            <label className="mb-2 block text-[11px] text-ink3">
              Установлен на
              <input className="input mt-1 h-9" value={linkForm.installed} onChange={(event) => setLinkForm({ ...linkForm, installed: event.target.value })} placeholder="оп.4 / КТП №4" />
            </label>
            <label className="mb-3 block text-[11px] text-ink3">
              Примечание
              <input className="input mt-1 h-9" value={linkForm.route} onChange={(event) => setLinkForm({ ...linkForm, route: event.target.value })} placeholder="вдоль дороги" />
            </label>
            <div className="flex gap-2">
              <button type="button" className="btn-primary h-9 flex-1" disabled={busy} onClick={() => void saveLink()}>
                Сохранить
              </button>
              <button type="button" className="btn-ghost h-9" onClick={() => setEditingLink(null)}>
                Отмена
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <p className="text-[11px] text-ink3">
        Цвета: <span style={{ color: POWER_COLOR.off }}>●</span> зелёный — кабель обесточен/свободен,{' '}
        <span style={{ color: POWER_COLOR.on }}>●</span> красный — под напряжением (на схеме и в карточке).
      </p>
    </div>
  )
}
