import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { Alert, Badge, ConfirmDialog, Field, PageTitle } from '../components/ui'
import { DynamicAssetFields, TypeGroupTabs } from '../components/asset/DynamicFields'
import { ApiError } from '../lib/api'
import type { AssetBrief, AssetType, ToggleResult } from '../lib/gis'
import { STATUS_COLOR, STATUS_LABEL, gisApi } from '../lib/gis'
import { PowerDot, PowerStateBadge } from '../components/asset/PowerStateBadge'
import { PowerToggleButton } from '../components/asset/PowerToggleButton'
import { cellKindTitle } from '../lib/equipmentTemplates'
import { voltageText } from '../lib/power'
import type { AttrValues, FieldErrors, TypeGroup } from '../lib/assetFields'
import {
  buildAttrs,
  cableLifecycleStatus,
  defaultAttrValues,
  groupOfType,
  groupTypes,
  mapServerFieldErrors,
  missingRequiredLabels,
  typeFields,
  typesOfGroup,
  validateAssetFields,
} from '../lib/assetFields'
import { openExport } from '../lib/dashboard'

type SortKey = 'code' | 'name' | 'type' | 'status' | 'x' | 'y'

/** Ошибки основных полей формы создания (не паспорта): имя, код, тип… */
type BaseFieldErrors = FieldErrors

export function RegistryPage() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const [items, setItems] = useState<AssetBrief[]>([])
  const [types, setTypes] = useState<AssetType[]>([])
  const [mapBounds, setMapBounds] = useState<{ x: number; y: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [parentFilter, setParentFilter] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'code', dir: 1 })
  const [notice, setNotice] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<AssetBrief | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [showGrouped, setShowGrouped] = useState(false)
  const [groupOpen, setGroupOpen] = useState(false)
  const [groupType, setGroupType] = useState('')
  const [groupName, setGroupName] = useState('')
  const [form, setForm] = useState({
    name: '',
    type_code: '',
    code: '',
    status: 'off',
    parent_id: '',
    location_text: '',
    x: '',
    y: '',
  })
  // Динамическая форма: класс → тип → поля паспорта (gis.asset_type_fields)
  const [activeClass, setActiveClass] = useState('')
  const [attrValues, setAttrValues] = useState<AttrValues>({})
  const [attrErrors, setAttrErrors] = useState<FieldErrors>({})
  const [baseErrors, setBaseErrors] = useState<BaseFieldErrors>({})
  const [formError, setFormError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [assetsData, typesData] = await Promise.all([
        gisApi.assets(),
        // with_fields=1 — поля паспорта для динамической формы создания
        gisApi.types({ with_fields: true }),
      ])
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
  useEffect(() => {
    gisApi
      .layer()
      .then((layer) => setMapBounds({ x: layer.width_m, y: layer.height_m }))
      .catch(() => setMapBounds(null))
  }, [])

  const parents = useMemo(
    () =>
      items
        .filter((item) => ['source', 'equipment'].includes(item.type.category) && item.type.code !== 'cell')
        .sort((a, b) => a.code.localeCompare(b.code)),
    [items],
  )

  // --- динамическая форма создания: класс → модель → поля паспорта ----------
  const typeGroups: TypeGroup[] = useMemo(() => groupTypes(types), [types])
  const activeGroupTypes = useMemo(() => typesOfGroup(typeGroups, activeClass), [typeGroups, activeClass])
  const selectedType = useMemo(
    () => types.find((type) => type.code === form.type_code) ?? null,
    [types, form.type_code],
  )
  const selectedFields = useMemo(() => (selectedType ? typeFields(selectedType) : []), [selectedType])

  const resetFormErrors = () => {
    setAttrErrors({})
    setBaseErrors({})
    setFormError(null)
  }

  /** Сменить тип: пересобрать поля и стартовые значения паспорта. */
  const applyType = (type: AssetType | null) => {
    setForm((prev) => ({ ...prev, type_code: type?.code ?? '' }))
    setAttrValues(type ? defaultAttrValues(typeFields(type)) : {})
    setAttrErrors({})
    setBaseErrors({})
    setFormError(null)
  }

  const openCreate = () => {
    const groups = groupTypes(types)
    // Помним последний выбранный тип, пока форма не создана (как раньше при «Отмене»)
    const remembered = types.find((type) => type.code === form.type_code) ?? null
    const current = remembered
      ? groups.find((group) => group.types.some((type) => type.code === remembered.code))
      : groups[0]
    const group = current ?? groups[0]
    const type = remembered ?? group?.types[0] ?? null
    setActiveClass(group?.group.code ?? '')
    setForm({
      name: '',
      type_code: type?.code ?? '',
      code: '',
      status: 'off',
      parent_id: '',
      location_text: '',
      x: '',
      y: '',
    })
    setAttrValues(type ? defaultAttrValues(typeFields(type)) : {})
    resetFormErrors()
    setCreateOpen(true)
  }

  const selectClass = (code: string) => {
    setActiveClass(code)
    applyType(typesOfGroup(typeGroups, code)[0] ?? null)
  }

  const selectType = (code: string) => {
    const type = types.find((item) => item.code === code) ?? null
    if (type) setActiveClass(groupOfType(type).code)
    applyType(type)
  }

  const changeAttr = (code: string, value: string) => {
    setAttrValues((prev) => ({ ...prev, [code]: value }))
    setAttrErrors((prev) => {
      if (!prev[code]) return prev
      const next = { ...prev }
      delete next[code]
      return next
    })
    setFormError(null)
  }

  // --- этап 2: переключение ячеек и разъединителей прямо из списка ----------
  const canSwitch = can('asset.status.edit')

  /** Ячейка БКРУ/ПС, разъединитель КТП или коммутационный аппарат. */
  const isSwitchable = (item: AssetBrief) =>
    Boolean(item.cell_kind) || item.type.equipment_class === 'switching' || item.type.code === 'razedinitel'

  const applyToggle = (result: ToggleResult) => {
    setItems((prev) =>
      prev.map((item) =>
        item.id === result.asset_id
          ? { ...item, status: result.status, grounded: result.grounded }
          : item,
      ),
    )
    setNotice(
      result.energized
        ? `${result.name}: включено — под напряжением, ${voltageText(true, result.voltage_kv)}`
        : `${result.name}: отключено — обесточено`,
    )
  }

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
    // Ячейки и разъединители — физические устройства с переключением, поэтому
    // показываем их и без галочки «вложенные»: иначе кнопки «Вкл/Откл» в списке
    // были бы недоступны для единственного места, где они вложены (ПС/БКРУ/КТП).
    if (!showGrouped) result = result.filter((item) => !item.grouped || isSwitchable(item))

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
  }, [items, search, typeFilter, statusFilter, parentFilter, sort, showGrouped])

  const createGroup = async () => {
    if (selected.size === 0) return
    setBusy(true)
    setError(null)
    try {
      await gisApi.groupAssets({
        parent_type_code: groupType || types[0]?.code || '',
        name: groupName.trim() || 'Группа',
        child_ids: Array.from(selected),
      })
      setNotice(`Собрана группа «${groupName || 'Группа'}»: ${selected.size} объектов`)
      setSelected(new Set())
      setSelectMode(false)
      setGroupOpen(false)
      setGroupName('')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось собрать группу')
    } finally {
      setBusy(false)
    }
  }

  const toggleSort = (key: SortKey) => {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === 1 ? -1 : 1 } : { key, dir: 1 }))
  }

  const nameLength = form.name.trim().length
  const nameTooLong = nameLength > 255
  const locationTooLong = form.location_text.trim().length > 255
  const hasX = Boolean(form.x.trim())
  const hasY = Boolean(form.y.trim())
  const coordsPartial = hasX !== hasY
  const coordsBad =
    (hasX && !Number.isFinite(Number(form.x.replace(',', '.')))) ||
    (hasY && !Number.isFinite(Number(form.y.replace(',', '.'))))
  const xNum = hasX ? Number(form.x.replace(',', '.')) : null
  const yNum = hasY ? Number(form.y.replace(',', '.')) : null
  const outOfBounds =
    Boolean(mapBounds) &&
    ((xNum !== null && Number.isFinite(xNum) && (xNum < 0 || xNum > mapBounds!.x)) ||
      (yNum !== null && Number.isFinite(yNum) && (yNum < 0 || yNum > mapBounds!.y)))
  const createBlocked =
    busy ||
    nameLength < 2 ||
    nameTooLong ||
    !form.type_code ||
    locationTooLong ||
    coordsPartial ||
    coordsBad ||
    outOfBounds
  const createAsset = async () => {
    // Клиентская проверка паспорта до отправки: обязательные/типы/min-max/список.
    const clientErrors = validateAssetFields(selectedFields, attrValues)
    if (Object.keys(clientErrors).length > 0) {
      setAttrErrors(clientErrors)
      setBaseErrors({})
      const missing = missingRequiredLabels(selectedFields, attrValues)
      setFormError(
        missing.length > 0
          ? `Заполните обязательные поля: ${missing.join(', ')}`
          : 'Проверьте поля паспорта: выделенные значения не подходят по типу',
      )
      return
    }
    setBusy(true)
    setFormError(null)
    setBaseErrors({})
    try {
      const payload: Parameters<typeof gisApi.create>[0] = {
        name: form.name.trim(),
        type_code: form.type_code,
        status: form.status,
        location_text: form.location_text.trim() || null,
      }
      if (form.code.trim()) payload.code = form.code.trim().toUpperCase()
      if (form.parent_id) payload.parent_id = form.parent_id
      if (form.x.trim() && form.y.trim()) {
        payload.x = Number(form.x.replace(',', '.'))
        payload.y = Number(form.y.replace(',', '.'))
      }
      const attrs = buildAttrs(selectedFields, attrValues)
      if (Object.keys(attrs).length > 0) payload.attrs = attrs
      // «Состояние кабеля» — не только attrs: у него отдельная колонка с CHECK (0015)
      const cableState = cableLifecycleStatus(selectedFields, attrValues)
      if (cableState) payload.lifecycle_status = cableState
      const created = await gisApi.create(payload)
      setNotice(
        created.x === null
          ? `Объект ${created.code} создан без координат — он в списке «Не размещённые»`
          : `Объект ${created.code} создан и размещён на карте`,
      )
      setCreateOpen(false)
      setForm({ name: '', type_code: '', code: '', status: 'off', parent_id: '', location_text: '', x: '', y: '' })
      setAttrValues({})
      resetFormErrors()
      await load()
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        // Серверная ошибка: `fields` — машинные ключи, `field_labels` — русские подписи.
        const mapped = mapServerFieldErrors(selectedFields, err.fields, err.fieldLabels)
        setAttrErrors(mapped.attrs)
        setBaseErrors(mapped.base)
        setFormError(
          mapped.summary ||
            err.message ||
            'Сервер отклонил данные: проверьте выделенные поля формы',
        )
      } else if (err instanceof ApiError) {
        setFormError(err.message)
      } else {
        setFormError('Не удалось создать объект: проверьте соединение и повторите')
      }
    } finally {
      setBusy(false)
    }
  }

  const deleteAsset = async (item: AssetBrief) => {
    setDeleting(true)
    setError(null)
    try {
      await gisApi.remove(item.id)
      setNotice(`Объект ${item.code} удалён из реестра`)
      setPendingDelete(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось удалить объект')
    } finally {
      setDeleting(false)
    }
  }

  const unplaced = useMemo(() => items.filter((item) => item.x === null || item.y === null), [items])

  const header = (key: SortKey, label: string) => (
    <th className="whitespace-nowrap px-3 py-2 font-medium">
      <button type="button" className="inline-flex items-center gap-1 hover:text-ink" onClick={() => toggleSort(key)}>
        {label}
        {sort.key === key ? <span className="text-accent">{sort.dir === 1 ? '▲' : '▼'}</span> : null}
      </button>
    </th>
  )

  /** Ошибка серверной валидации под основным полем формы (по ключу `fields`). */
  const baseError = (key: string) =>
    baseErrors[key] ? (
      <span role="alert" className="mt-1 block text-[12px] text-danger">
        {baseErrors[key]}
      </span>
    ) : null

  return (
    <div className="space-y-4">
      <PageTitle
        title="Реестр оборудования"
        subtitle="Все объекты карьера: тип, состояние, родитель, координаты. Админ может разместить объект на карте"
      />

      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      {unplaced.length > 0 ? (
        <div className="card flex flex-wrap items-center gap-2 text-[12px] text-ink2">
          <Badge tone="warm">Не размещённые</Badge>
          <span>объектов без координат: {unplaced.length}</span>
          <button
            type="button"
            className="text-[12px] text-accent"
            onClick={() => {
              setParentFilter('')
              setStatusFilter('')
              setTypeFilter('')
              setSearch('')
              setSort({ key: 'code', dir: 1 })
            }}
          >
            показать все
          </button>
          <span className="text-ink3">— разместите их на карте кнопкой «Разместить»</span>
        </div>
      ) : null}

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
            {typeGroups.map(({ group, types: groupTypesList }) => (
              <optgroup key={group.code} label={`${group.icon} ${group.title}`}>
                {groupTypesList.map((type) => (
                  <option key={type.code} value={type.code}>
                    {type.name}
                  </option>
                ))}
              </optgroup>
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
        {can('asset.create') ? (
          <button
            type="button"
            className={`h-10 px-3 text-[12px] ${selectMode ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => {
              setSelectMode((prev) => !prev)
              setSelected(new Set())
            }}
          >
            {selectMode ? 'Выбор: ' + selected.size : 'Выбрать'}
          </button>
        ) : null}
        {can('asset.create') && selectMode && selected.size > 0 ? (
          <button
            type="button"
            className="btn-primary h-10 px-3 text-[12px]"
            onClick={() => {
              setGroupType(types[0]?.code ?? '')
              setGroupOpen(true)
            }}
          >
            Собрать в группу
          </button>
        ) : null}
        <label className="flex items-center gap-1.5 text-[12px] text-ink3">
          <input type="checkbox" checked={showGrouped} onChange={(e) => setShowGrouped(e.target.checked)} />
          вложенные
        </label>
        {can('asset.create') ? (
          <button
            type="button"
            className="btn-primary admin-only h-10 px-3 text-[12px]"
            onClick={openCreate}
          >
            + Объект
          </button>
        ) : null}
        <span className="ml-auto text-[12px] text-ink3">Показано {rows.length} из {items.length}</span>
      </div>

      <div className="space-y-2 md:hidden">
        {rows.map((item) => (
          <div key={item.id} className="card p-4">
            <div className="flex items-start justify-between gap-2">
              {selectMode ? (
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4"
                  checked={selected.has(item.id)}
                  onChange={() =>
                    setSelected((prev) => {
                      const next = new Set(prev)
                      if (next.has(item.id)) next.delete(item.id)
                      else next.add(item.id)
                      return next
                    })
                  }
                />
              ) : null}
              <div className="min-w-0">
                <div className="font-mono text-[12px] text-ink3">{item.code}</div>
                <div className="truncate text-[15px] font-medium">{item.name}</div>
                <div className="mt-0.5 text-[12px] text-ink2">
                  {item.type.icon} {item.type.name}
                  {item.is_mobile ? ' · мобильный' : ''}
                </div>
                {item.cell_kind ? (
                  <div className="mt-0.5 text-[11px] text-ink3">
                    №{item.cell_no ?? '—'} · {cellKindTitle(item.cell_kind)}
                    {item.section_no != null ? ` · секция ${item.section_no}` : ''}
                  </div>
                ) : null}
              </div>
              {isSwitchable(item) ? (
                <div className="flex flex-col items-end gap-1">
                  <PowerStateBadge status={item.status} grounded={item.grounded} size="sm" />
                  {canSwitch ? (
                    <PowerToggleButton
                      assetId={item.id}
                      name={item.name}
                      status={item.status}
                      grounded={item.grounded}
                      compact
                      onToggled={applyToggle}
                    />
                  ) : null}
                </div>
              ) : (
                <span
                  className="shrink-0 rounded-full px-2 py-1 text-[12px]"
                  style={{ background: `${STATUS_COLOR[item.status]}22`, color: STATUS_COLOR[item.status] }}
                >
                  {STATUS_LABEL[item.status] ?? item.status}
                </span>
              )}
            </div>
            <div className="mt-2 text-[12px] text-ink3">
              X {item.x ?? '—'} · Y {item.y ?? '—'}
              {item.grounded ? ' · заземлён' : ''}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                className="btn-ghost h-11 flex-1 px-3 text-[13px]"
                onClick={() => navigate('/map', { state: { openAssetId: item.id } })}
              >
                Открыть
              </button>
              {can('asset.create') ? (
                <>
                  <button
                    type="button"
                    className="btn-ghost h-11 flex-1 px-3 text-[13px]"
                    onClick={() => navigate('/map', { state: { placeAssetId: item.id } })}
                  >
                    {item.x === null ? 'Разместить' : 'Переместить'}
                  </button>
                  <button
                    type="button"
                    className="btn-ghost admin-only h-11 px-3 text-[13px] text-warm"
                    title="Удалить объект"
                    aria-label={`Удалить объект ${item.code}`}
                    onClick={() => setPendingDelete(item)}
                  >
                    🗑
                  </button>
                </>
              ) : null}
            </div>
          </div>
        ))}
        {rows.length === 0 ? <div className="card text-[13px] text-ink3">Ничего не найдено</div> : null}
      </div>

      <div className="card hidden overflow-x-auto p-0 md:block">
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
                {selectMode ? (
                  <td className="px-2 py-2">
                    <input
                      type="checkbox"
                      className="h-4 w-4"
                      checked={selected.has(item.id)}
                      onChange={() =>
                        setSelected((prev) => {
                          const next = new Set(prev)
                          if (next.has(item.id)) next.delete(item.id)
                          else next.add(item.id)
                          return next
                        })
                      }
                    />
                  </td>
                ) : null}
                <td className="whitespace-nowrap px-3 py-2 font-mono text-[12px]">{item.code}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span>{item.type.icon}</span>
                    <span>{item.name}</span>
                    {item.cell_kind ? (
                      <span className="rounded border border-line px-1.5 py-0.5 text-[10px] text-ink3">
                        №{item.cell_no ?? '—'} · {cellKindTitle(item.cell_kind)}
                      </span>
                    ) : null}
                    {item.is_mobile ? <Badge tone="accent">мобильный</Badge> : null}
                  </div>
                </td>
                <td className="px-3 py-2 text-ink2">{item.type.name}</td>
                <td className="whitespace-nowrap px-3 py-2">
                  {isSwitchable(item) ? (
                    <PowerStateBadge status={item.status} grounded={item.grounded} size="sm" />
                  ) : (
                    <span className="inline-flex items-center gap-1.5">
                      <PowerDot status={item.status} grounded={item.grounded} />
                      {STATUS_LABEL[item.status] ?? item.status}
                      {item.grounded ? <span className="text-ground">⏚</span> : null}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 font-mono text-[12px] text-ink2">{item.x ?? '—'}</td>
                <td className="px-3 py-2 font-mono text-[12px] text-ink2">{item.y ?? '—'}</td>
                <td className="px-3 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {canSwitch && isSwitchable(item) ? (
                      <PowerToggleButton
                        assetId={item.id}
                        name={item.name}
                        status={item.status}
                        grounded={item.grounded}
                        compact
                        onToggled={applyToggle}
                      />
                    ) : null}
                    <button
                      type="button"
                      className="btn-ghost h-8 px-2.5 text-[12px]"
                      onClick={() => navigate('/map', { state: { openAssetId: item.id } })}
                    >
                      На карте
                    </button>
                    {can('asset.create') ? (
                      <>
                        <button
                          type="button"
                          className="btn-ghost h-8 px-2.5 text-[12px]"
                          onClick={() => navigate('/map', { state: { placeAssetId: item.id } })}
                        >
                          {item.x === null ? 'Разместить' : 'Переместить'}
                        </button>
                        <button
                          type="button"
                          className="btn-ghost admin-only h-8 px-2.5 text-[12px] text-warm"
                          title="Удалить объект"
                          aria-label={`Удалить объект ${item.code}`}
                          onClick={() => setPendingDelete(item)}
                        >
                          🗑
                        </button>
                      </>
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

      {createOpen ? (
        <div className="modal-safe fixed inset-0 z-[1400] flex items-end justify-center bg-black/60 sm:items-center sm:p-4">
          <div className="max-h-[calc(100dvh-var(--bottom-nav)-16px)] w-full max-w-2xl overflow-y-auto md:max-h-[92vh] rounded-t-2xl border border-line bg-surface1 p-4 sm:rounded-2xl">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[16px] font-semibold">Новый объект</h2>
              <button type="button" className="btn-ghost h-9 px-3 text-[12px]" onClick={() => setCreateOpen(false)}>
                Закрыть
              </button>
            </div>
            {formError ? (
              <div className="mb-3">
                <Alert kind="error">{formError}</Alert>
              </div>
            ) : null}
            <div className="mb-3 space-y-1.5">
              <span className="label">Класс оборудования</span>
              <TypeGroupTabs groups={typeGroups} value={activeClass} onChange={selectClass} />
              <span className="block text-[11px] text-ink3">
                {selectedType
                  ? `Тип: ${selectedType.name} · полей паспорта: ${selectedFields.length}`
                  : 'Выберите класс и модель оборудования'}
              </span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <Field label="Название">
                  <input
                    className="input"
                    value={form.name}
                    maxLength={255}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="КТП-20 (новая)"
                  />
                  {baseError('name')}
                </Field>
              </div>
              <Field label="Модель (тип)">
                <select
                  className="input"
                  value={form.type_code}
                  onChange={(e) => selectType(e.target.value)}
                >
                  {activeGroupTypes.length === 0 ? <option value="">— в классе нет типов —</option> : null}
                  {activeGroupTypes.map((type) => (
                    <option key={type.code} value={type.code}>
                      {type.icon ? `${type.icon} ` : ''}
                      {type.name}
                    </option>
                  ))}
                </select>
                {baseError('type_code')}
              </Field>
              <Field label="Код (необязательно)">
                <input
                  className="input"
                  value={form.code}
                  onChange={(e) => setForm({ ...form, code: e.target.value })}
                  placeholder="сгенерируется автоматически"
                />
                {baseError('code')}
              </Field>
              <Field label="Состояние">
                <select
                  className="input"
                  value={form.status}
                  onChange={(e) => setForm({ ...form, status: e.target.value })}
                >
                  {Object.entries(STATUS_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                {baseError('status')}
              </Field>
              <Field label="Родительский объект (необязательно)">
                <select
                  className="input"
                  value={form.parent_id}
                  onChange={(e) => setForm({ ...form, parent_id: e.target.value })}
                >
                  <option value="">— без родителя —</option>
                  {parents.map((parent) => (
                    <option key={parent.id} value={parent.id}>
                      {parent.code} · {parent.name}
                    </option>
                  ))}
                </select>
                {baseError('parent_id')}
              </Field>
              <Field label="Расположение (текстом)">
                <input
                  className="input"
                  value={form.location_text}
                  onChange={(e) => setForm({ ...form, location_text: e.target.value })}
                  placeholder="Гор. +120, борт северный"
                />
                {baseError('location_text')}
              </Field>
              <Field label="X, м (необязательно)">
                <input
                  className="input"
                  value={form.x}
                  onChange={(e) => setForm({ ...form, x: e.target.value })}
                  placeholder="можно оставить пустым"
                />
                {baseError('x')}
              </Field>
              <Field label="Y, м (необязательно)">
                <input
                  className="input"
                  value={form.y}
                  onChange={(e) => setForm({ ...form, y: e.target.value })}
                  placeholder="можно оставить пустым"
                />
                {baseError('y')}
              </Field>
            </div>
            <div className="mt-4 border-t border-line pt-3">
              <h3 className="mb-2 text-[13px] font-semibold">Паспорт оборудования</h3>
              <DynamicAssetFields
                fields={selectedFields}
                values={attrValues}
                errors={attrErrors}
                disabled={busy}
                onChange={changeAttr}
              />
            </div>
            <p className="mt-2 text-[11px] text-ink3">
              Без координат объект создастся сразу и попадёт в список «Не размещённые»; на карту его можно
              поставить позже кнопкой «Разместить».
            </p>
            {nameTooLong ? (
              <p className="mt-1 text-[11px] text-danger">Название: максимум 255 символов</p>
            ) : null}
            {locationTooLong ? (
              <p className="mt-1 text-[11px] text-danger">Расположение: максимум 255 символов</p>
            ) : null}
            {coordsPartial ? (
              <p className="mt-1 text-[11px] text-danger">Укажите обе координаты X и Y — или оставьте обе пустыми</p>
            ) : null}
            {coordsBad ? (
              <p className="mt-1 text-[11px] text-danger">Координаты должны быть числами, например 1250,5</p>
            ) : null}
            {outOfBounds ? (
              <p className="mt-1 text-[11px] text-danger">
                Координаты вне карты: допустимо X 0…{Math.round(mapBounds?.x ?? 0)} м, Y 0…
                {Math.round(mapBounds?.y ?? 0)} м. Это метры карьера, а не координаты СК-42.
              </p>
            ) : null}
            {!outOfBounds && mapBounds ? (
              <p className="mt-1 text-[11px] text-ink3">
                Допустимые координаты: X 0…{Math.round(mapBounds.x)} м, Y 0…{Math.round(mapBounds.y)} м.
              </p>
            ) : null}
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                className="btn-primary px-5"
                disabled={createBlocked}
                onClick={() => void createAsset()}
              >
                {busy ? 'Создаём…' : 'Создать объект'}
              </button>
              <button type="button" className="btn-ghost" onClick={() => setCreateOpen(false)}>
                Отмена
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {groupOpen ? (
        <div className="fixed inset-0 z-[1400] flex items-end justify-center bg-black/60 p-3 sm:items-center">
          <div className="card modal-safe w-full max-w-md p-4">
            <div className="mb-3 text-[15px] font-semibold">Собрать в группу</div>
            <p className="mb-3 text-[12px] text-ink3">
              Выбрано объектов: {selected.size}. Будет создан родительский объект, выбранные объекты
              станут его составом: на карте — одна иконка, на схеме — рамка с подписью.
            </p>
            <label className="mb-2 block text-[12px]">
              <span className="label">Тип родительского объекта</span>
              <select className="input h-9" value={groupType} onChange={(e) => setGroupType(e.target.value)}>
                {typeGroups.map(({ group, types: groupTypesList }) => (
                  <optgroup key={group.code} label={group.title}>
                    {groupTypesList.map((type) => (
                      <option key={type.code} value={type.code}>
                        {type.name}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <label className="mb-3 block text-[12px]">
              <span className="label">Название</span>
              <input className="input h-9" value={groupName} onChange={(e) => setGroupName(e.target.value)} placeholder="ПС 35/6 кВ «Карьер»" />
            </label>
            <div className="flex gap-2">
              <button type="button" className="btn-primary h-9 flex-1" disabled={busy} onClick={() => void createGroup()}>
                Собрать
              </button>
              <button type="button" className="btn-ghost h-9" onClick={() => setGroupOpen(false)}>Отмена</button>
            </div>
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title={pendingDelete ? `Удалить объект «${pendingDelete.code}»?` : 'Удалить объект?'}
        message={
          pendingDelete
            ? `${pendingDelete.name}. Объект исчезнет из реестра и с карты, история и журнал аудита сохранятся.`
            : undefined
        }
        confirmLabel="Удалить"
        busy={deleting}
        onConfirm={() => (pendingDelete ? deleteAsset(pendingDelete) : undefined)}
        onCancel={() => setPendingDelete(null)}
      />

    </div>
  )
}
