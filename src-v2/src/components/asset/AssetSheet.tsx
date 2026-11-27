import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge, ConfirmDialog, Field } from '../ui'
import { ApiError } from '../../lib/api'
import type { AssetOut, CableRecord, ChildAsset, PowerPath } from '../../lib/gis'
import { STATUS_COLOR, STATUS_LABEL, gisApi } from '../../lib/gis'
import { cellKindTitle } from '../../lib/equipmentTemplates'
import type { PowerStateUpdate } from '../../lib/power'
import { StateControls } from './StateControls'
import { PowerStateBadge } from './PowerStateBadge'
import { DocumentsTab } from './DocumentsTab'
import { PhotosTab } from './PhotosTab'
import { HistoryTab } from './HistoryTab'
import { MaintenanceTab } from './MaintenanceTab'
import { ChildrenModal } from './ChildrenModal'
import { QrModal } from '../QrModal'
import { openExport } from '../../lib/dashboard'

interface Props {
  assetId: string
  onOpenAsset: (id: string) => void
  canManage: boolean
  canSwitch: boolean
  canManageDocs: boolean
  onMove?: (asset: AssetOut) => void
  /** Вызывается после успешного удаления: родитель закрывает карточку и обновляет список. */
  onDeleted?: (assetId: string) => void
  /**
   * F1: успешное переключение питания/заземления (StateControls, дети блока).
   * MapPage обновляет локальные `assets`/`assetStates`, чтобы схема перекрасилась
   * сразу, без перезагрузки страницы.
   */
  onStateChanged?: (update: PowerStateUpdate) => void
}

type Tab = 'passport' | 'photos' | 'docs' | 'history' | 'maintenance'

const ATTR_LABELS: Record<string, string> = {
  power_kw: 'Мощность, кВт',
  power_kva: 'Мощность, кВА',
  voltage_in_kv: 'Напряжение входа, кВ',
  voltage_out_kv: 'Напряжение выхода, кВ',
  fuel_type: 'Топливо',
  drive_type: 'Привод',
  bucket_m3: 'Ковш, м³',
  section_breaker: 'Секционный выключатель',
}

const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'passport', label: 'Паспорт' },
  { key: 'photos', label: 'Фото' },
  { key: 'docs', label: 'Документы' },
  { key: 'history', label: 'История' },
]

/** Состояния кабеля (этап 2 кабельного учёта). */
const CABLE_STATE_LABEL: Record<string, string> = {
  installed: 'на оборудовании',
  reserve: 'в запасе',
  repair: 'в ремонте',
}

/** Считается ли объект переключаемым: ячейка ПС/БКРУ, разъединитель, коммутационный аппарат. */
function isSwitchableAsset(asset: AssetOut): boolean {
  return (
    Boolean(asset.cell_kind) ||
    asset.type.equipment_class === 'switching' ||
    asset.type.code === 'razedinitel'
  )
}

/** Номинал напряжения: паспорт ячейки → порт → null. */
function nominalVoltageOf(asset: AssetOut): number | null {
  const raw = Number(asset.attrs?.voltage_kv)
  if (Number.isFinite(raw) && raw > 0) return raw
  const port = asset.ports.find((item) => item.nominal_voltage_kv != null)
  return port?.nominal_voltage_kv ?? null
}

function isCableAsset(asset: AssetOut): boolean {
  return (
    asset.type.equipment_class === 'cable' ||
    asset.type.code === 'cable' ||
    asset.lifecycle_status != null
  )
}

export function AssetSheet({ assetId, onOpenAsset, canManage, canSwitch, canManageDocs, onMove, onDeleted, onStateChanged }: Props) {
  const [asset, setAsset] = useState<AssetOut | null>(null)
  const [path, setPath] = useState<PowerPath | null>(null)
  const [children, setChildren] = useState<ChildAsset[]>([])
  /** Кабельный учёт: статус и привязка кабеля-объекта (этап 2). */
  const [cable, setCable] = useState<CableRecord | null>(null)
  const [tab, setTab] = useState<Tab>('passport')
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [editOpen, setEditOpen] = useState(false)
  const [editSaving, setEditSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [editForm, setEditForm] = useState({
    name: '',
    code: '',
    status: 'off',
    location_text: '',
    power: '',
  })
  const [showChildren, setShowChildren] = useState(false)
  const [showQr, setShowQr] = useState(false)

  const load = useCallback(async () => {
    try {
      const [detail, powerPath, kids] = await Promise.all([
        gisApi.asset(assetId),
        gisApi.powerPath(assetId),
        gisApi.children(assetId),
      ])
      setAsset(detail)
      setPath(powerPath)
      setChildren(kids)
      setError(null)
      if (isCableAsset(detail)) {
        // Привязка кабеля (участок/объект) приходит только из кабельного учёта.
        const cables = await gisApi.cables().catch(() => [] as CableRecord[])
        setCable(cables.find((item) => item.id === detail.id) ?? null)
      } else {
        setCable(null)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить объект')
    }
  }, [assetId])

  useEffect(() => {
    setAsset(null)
    setPath(null)
    setChildren([])
    setCable(null)
    setTab('passport')
    setConfirmDelete(false)
    void load()
  }, [assetId, load])

  if (error) return <Alert kind="error">{error}</Alert>
  if (!asset) return <div className="py-6 text-center text-[13px] text-ink3">Загружаем карточку…</div>

  const statusColor = STATUS_COLOR[asset.status] ?? '#6B7A8A'
  const attrs = Object.entries(asset.attrs ?? {})
  const switchable = isSwitchableAsset(asset)
  const nominalVoltage = nominalVoltageOf(asset)

  const openEditor = () => {
    setEditForm({
      name: asset.name,
      code: asset.code,
      status: asset.status,
      location_text: asset.location_text ?? '',
      power: asset.attrs?.power_kw !== undefined ? String(asset.attrs.power_kw) : '',
    })
    setEditError(null)
    setEditOpen(true)
  }

  const saveEditor = async () => {
    setEditSaving(true)
    setEditError(null)
    try {
      const nextAttrs: Record<string, unknown> = { ...(asset.attrs ?? {}) }
      if (editForm.power.trim()) nextAttrs.power_kw = Number(editForm.power.replace(',', '.'))
      else delete nextAttrs.power_kw

      await gisApi.update(asset.id, {
        name: editForm.name.trim(),
        code: editForm.code.trim().toUpperCase(),
        status: editForm.status,
        location_text: editForm.location_text.trim() || null,
        attrs: nextAttrs,
      })
      setEditOpen(false)
      await load()
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : 'Не удалось сохранить карточку')
    } finally {
      setEditSaving(false)
    }
  }

  const deleteAsset = async () => {
    setDeleteBusy(true)
    setDeleteError(null)
    try {
      await gisApi.remove(asset.id)
      setConfirmDelete(false)
      onDeleted?.(asset.id)
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : 'Не удалось удалить объект')
    } finally {
      setDeleteBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3">
        <div
          className="grid h-12 w-12 shrink-0 place-items-center rounded-xl text-xl"
          style={{ background: `${asset.type.color}22` }}
        >
          {asset.type.icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[17px] font-semibold leading-tight">{asset.name}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-ink2">
            <span className="font-mono">{asset.code}</span>
            {switchable ? (
              <PowerStateBadge
                status={asset.status}
                grounded={asset.grounded}
                voltageKv={nominalVoltage}
                size="sm"
              />
            ) : (
              <span
                className="inline-flex items-center gap-1 rounded-full px-2 py-0.5"
                style={{ background: `${statusColor}22`, color: statusColor }}
              >
                ● {STATUS_LABEL[asset.status] ?? asset.status}
              </span>
            )}
            {asset.cell_kind ? (
              <Badge tone="neutral">
                №{asset.cell_no ?? '—'} · {cellKindTitle(asset.cell_kind)}
                {asset.section_no != null ? ` · секция ${asset.section_no}` : ''}
              </Badge>
            ) : null}
            {path?.energized && asset.status !== 'on' ? <Badge tone="ok">питание есть</Badge> : null}
            {asset.grounded ? <Badge tone="warm">⏚ заземлено</Badge> : null}
            {asset.is_mobile ? <Badge tone="accent">мобильный</Badge> : null}
          </div>
        </div>
        {onMove && asset.is_mobile ? (
          <button
            type="button"
            className="btn-primary h-9 px-2.5 text-[12px]"
            title="Переместить объект"
            onClick={() => onMove(asset)}
          >
            🚚
          </button>
        ) : null}
        <button
          type="button"
          className="btn-ghost h-9 w-9 shrink-0 p-0 text-[13px]"
          title="QR-код объекта"
          onClick={() => setShowQr(true)}
        >
          ▦
        </button>
      </div>

      <div className="-mx-1 flex gap-1 overflow-x-auto rounded-xl border border-line bg-surface2/50 p-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {(asset?.type.has_maintenance ? [...TABS, { key: 'maintenance' as Tab, label: 'ТО' }] : TABS).map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            className={`min-h-[44px] shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-[13px] ${
              tab === item.key ? 'bg-surface1 text-ink' : 'text-ink2'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === 'passport' ? (
        <>
          <div className="grid grid-cols-2 gap-2 text-[13px]">
            <InfoCell
              label="Координаты"
              value={asset.x !== null && asset.y !== null ? `X ${asset.x} · Y ${asset.y} м` : '—'}
            />
            <InfoCell label="Расположение" value={asset.location_text ?? '—'} />
            <button
              type="button"
              className="rounded-lg bg-surface2/60 px-2.5 py-2 text-left"
              onClick={() => asset.parent_id && onOpenAsset(asset.parent_id)}
              disabled={!asset.parent_id}
            >
              <div className="text-[11px] text-ink3">Входит в</div>
              <div className="mt-0.5 break-words text-ink">{asset.parent_name ?? '—'}</div>
            </button>
            <InfoCell label="Портов" value={String(asset.ports.length)} />
          </div>

          {cable || isCableAsset(asset) ? (
            <div>
              <div className="mb-1 text-[12px] uppercase tracking-wide text-ink3">Кабельный учёт</div>
              <div className="grid grid-cols-2 gap-2 text-[13px]">
                <InfoCell
                  label="Состояние кабеля"
                  value={CABLE_STATE_LABEL[cable?.lifecycle_status ?? asset.lifecycle_status ?? ''] ?? '—'}
                />
                <InfoCell label="Марка" value={cable?.cable_mark ?? '—'} />
                <InfoCell
                  label="Сечение"
                  value={cable?.section_mm2 != null ? `${cable.section_mm2} мм²` : '—'}
                />
                <InfoCell label="Длина" value={cable?.length_m != null ? `${cable.length_m} м` : '—'} />
                <div className="col-span-2 rounded-lg bg-surface2/60 px-2.5 py-2">
                  <div className="text-[11px] text-ink3">Привязка</div>
                  <div className="mt-0.5 break-words text-ink">
                    {cable?.link_label ?? cable?.installed_on ?? 'не установлен (свободен)'}
                  </div>
                  {cable?.from_asset && cable?.to_asset ? (
                    <div className="mt-0.5 text-[11px] text-ink3">
                      {cable.from_asset.name} → {cable.to_asset.name}
                    </div>
                  ) : null}
                  <div className="mt-1 text-[11px] text-ink3">
                    Установка и снятие — на странице «Кабели», вкладки «На оборудовании / В запасе /
                    В ремонте».
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {attrs.length > 0 ? (
            <div>
              <div className="mb-1 text-[12px] uppercase tracking-wide text-ink3">Характеристики</div>
              <div className="grid grid-cols-2 gap-2 text-[13px]">
                {attrs.map(([key, value]) => (
                  <InfoCell
                    key={key}
                    label={ATTR_LABELS[key] ?? key}
                    value={typeof value === 'boolean' ? (value ? 'да' : 'нет') : String(value)}
                  />
                ))}
              </div>
            </div>
          ) : null}

          <div>
            <div className="mb-1 text-[12px] uppercase tracking-wide text-ink3">Порты</div>
            <div className="flex flex-wrap gap-1.5">
              {asset.ports.map((port) => (
                <span
                  key={port.id}
                  className={`rounded-lg border px-2 py-1 text-[12px] ${
                    port.kind === 'in'
                      ? 'border-ok/40 text-ok'
                      : port.kind === 'out'
                        ? 'border-warm/40 text-warm'
                        : 'border-line text-ink2'
                  }`}
                >
                  {port.code} · {port.nominal_voltage_kv ? `${port.nominal_voltage_kv} кВ` : port.name}
                </span>
              ))}
              {asset.ports.length === 0 ? <span className="text-[12px] text-ink3">Порты не заданы</span> : null}
            </div>
          </div>

          <div>
            <div className="mb-1 text-[12px] uppercase tracking-wide text-ink3">Путь питания</div>
            {path?.chain.length ? (
              <div className="space-y-1">
                {path.chain.map((node, index) => (
                  <div key={`${node.id}-${index}`} className="flex items-center gap-2 text-[12px]">
                    <span
                      className={`w-[10px] shrink-0 rounded-full ${node.role === 'asset' ? 'bg-accent' : 'bg-line'}`}
                      style={{ height: 10 }}
                    />
                    <span className={node.role === 'asset' ? 'text-accent' : 'text-ink2'}>{node.name}</span>
                    {node.link_label ? (
                      <span className="text-[11px] text-ink3">← {node.link_label}</span>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[12px] text-ink3">{path?.reason ?? 'Путь не найден'}</p>
            )}
            {path && !path.energized && path.reason ? (
              <p className="mt-1 text-[12px] text-warm">{path.reason}</p>
            ) : null}
          </div>

          {canSwitch ? (
            <div>
              <div className="mb-1 flex items-center gap-2 text-[12px] uppercase tracking-wide text-ink3">
                <span>Оперативное состояние</span>
                {switchable ? (
                  <span className="rounded border border-line px-1.5 py-0.5 text-[10px] normal-case tracking-normal text-ink3">
                    переключение через toggle-API · аудит
                  </span>
                ) : null}
              </div>
              <StateControls
                asset={asset}
                onChanged={(next) => {
                  setAsset(next)
                  // F1: сообщаем карте/схеме — иначе цвет на холсте остаётся прежним
                  onStateChanged?.({ id: next.id, status: next.status, grounded: next.grounded })
                }}
                switchable={switchable}
              />
            </div>
          ) : null}

          <div className="flex flex-wrap gap-2 pt-1">
            {canManage ? (
              <button type="button" className="btn-ghost admin-only h-10 px-3 text-[13px]" onClick={openEditor}>
                ✎ Редактировать
              </button>
            ) : null}
            {onMove && asset.is_mobile ? (
              <button type="button" className="btn-primary h-10 px-3 text-[13px]" onClick={() => onMove(asset)}>
                🚚 Переместить
              </button>
            ) : null}
            <button
              type="button"
              className="btn-ghost h-10 px-3 text-[13px]"
              onClick={() => void openExport('passport', asset.id)}
            >
              ⬇ Паспорт (PDF)
            </button>
            {children.length > 0 ? (
              <button type="button" className="btn-primary h-10 px-3 text-[13px]" onClick={() => setShowChildren(true)}>
                Внутренняя схема · {children.length}
              </button>
            ) : null}
            {canManage ? (
              <button
                type="button"
                className="btn-ghost h-10 px-3 text-[13px] text-bad"
                onClick={() => setConfirmDelete(true)}
              >
                Удалить
              </button>
            ) : null}
          </div>
          {deleteError ? (
            <div className="pt-1">
              <Alert kind="error">{deleteError}</Alert>
            </div>
          ) : null}
        </>
      ) : null}

      {tab === 'photos' ? <PhotosTab assetId={asset.id} assetCode={asset.code} /> : null}
      {tab === 'docs' ? <DocumentsTab assetId={asset.id} canManage={canManageDocs} /> : null}
      {tab === 'history' ? <HistoryTab assetId={asset.id} /> : null}
      {tab === 'maintenance' ? <MaintenanceTab assetId={asset.id} /> : null}

      {showChildren ? (
        <ChildrenModal
          parentId={asset.id}
          title={`Состав: ${asset.name}`}
          children={children}
          canSwitch={canSwitch}
          onClose={() => setShowChildren(false)}
          onChanged={(updated) => {
            setChildren((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
            // F1: переключение ячейки во «внутренней схеме» тоже красит холст сразу
            onStateChanged?.({ id: updated.id, status: updated.status, grounded: updated.grounded })
          }}
        />
      ) : null}

      <QrModal
        open={showQr}
        asset={{ id: asset.id, code: asset.code, name: asset.name }}
        onClose={() => setShowQr(false)}
      />

      {editOpen ? (
        <div className="modal-safe fixed inset-0 z-[1400] flex items-end justify-center bg-black/60 sm:items-center sm:p-4">
          <div className="max-h-[calc(100dvh-var(--bottom-nav)-16px)] w-full max-w-lg overflow-y-auto rounded-t-2xl border border-line bg-surface1 p-4 md:max-h-none sm:rounded-2xl">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[16px] font-semibold">Редактирование объекта</h2>
              <button
                type="button"
                className="btn-ghost h-9 px-3 text-[12px]"
                onClick={() => setEditOpen(false)}
              >
                Закрыть
              </button>
            </div>

            {editError ? <Alert kind="error">{editError}</Alert> : null}

            <div className="mt-3 space-y-3">
              <Field label="Название">
                <input
                  className="input"
                  value={editForm.name}
                  onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Код">
                  <input
                    className="input font-mono"
                    value={editForm.code}
                    onChange={(e) => setEditForm({ ...editForm, code: e.target.value })}
                  />
                </Field>
                <Field label="Тип">
                  <input className="input" value={asset.type.name} disabled />
                </Field>
                <Field label="Состояние">
                  <select
                    className="input"
                    value={editForm.status}
                    onChange={(e) => setEditForm({ ...editForm, status: e.target.value })}
                  >
                    {Object.entries(STATUS_LABEL).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Мощность, кВт">
                  <input
                    className="input"
                    value={editForm.power}
                    onChange={(e) => setEditForm({ ...editForm, power: e.target.value })}
                    placeholder="например 250"
                  />
                </Field>
              </div>
              <Field label="Расположение">
                <input
                  className="input"
                  value={editForm.location_text}
                  onChange={(e) => setEditForm({ ...editForm, location_text: e.target.value })}
                />
              </Field>
            </div>

            <div className="mt-4 flex gap-2">
              <button
                type="button"
                className="btn-primary px-5"
                disabled={editSaving || editForm.name.trim().length < 2}
                onClick={() => void saveEditor()}
              >
                {editSaving ? 'Сохраняем…' : 'Сохранить'}
              </button>
              <button type="button" className="btn-ghost" onClick={() => setEditOpen(false)}>
                Отмена
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmDelete}
        title="Удалить объект?"
        message={`«${asset.name}» (${asset.code}) исчезнет из реестра и с карты. История, документы и журнал аудита сохранятся.`}
        confirmLabel="Удалить"
        busy={deleteBusy}
        onConfirm={deleteAsset}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  )
}

function InfoCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-surface2/60 px-2.5 py-2">
      <div className="text-[11px] text-ink3">{label}</div>
      <div className="mt-0.5 break-words text-ink">{value}</div>
    </div>
  )
}
