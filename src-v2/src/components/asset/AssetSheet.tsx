import { useCallback, useEffect, useState } from 'react'
import { Alert, Badge } from '../ui'
import { ApiError } from '../../lib/api'
import type { AssetOut, ChildAsset, PowerPath } from '../../lib/gis'
import { STATUS_COLOR, STATUS_LABEL, gisApi } from '../../lib/gis'
import { StateControls } from './StateControls'
import { DocumentsTab } from './DocumentsTab'
import { PhotosTab } from './PhotosTab'
import { HistoryTab } from './HistoryTab'
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
}

type Tab = 'passport' | 'photos' | 'docs' | 'history'

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

export function AssetSheet({ assetId, onOpenAsset, canManage, canSwitch, canManageDocs, onMove }: Props) {
  const [asset, setAsset] = useState<AssetOut | null>(null)
  const [path, setPath] = useState<PowerPath | null>(null)
  const [children, setChildren] = useState<ChildAsset[]>([])
  const [tab, setTab] = useState<Tab>('passport')
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
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
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить объект')
    }
  }, [assetId])

  useEffect(() => {
    setAsset(null)
    setPath(null)
    setChildren([])
    setTab('passport')
    setConfirmDelete(false)
    void load()
  }, [assetId, load])

  if (error) return <Alert kind="error">{error}</Alert>
  if (!asset) return <div className="py-6 text-center text-[13px] text-ink3">Загружаем карточку…</div>

  const statusColor = STATUS_COLOR[asset.status] ?? '#6B7A8A'
  const attrs = Object.entries(asset.attrs ?? {})

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
            <span
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5"
              style={{ background: `${statusColor}22`, color: statusColor }}
            >
              ● {STATUS_LABEL[asset.status] ?? asset.status}
            </span>
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

      <div className="flex gap-1 rounded-xl border border-line bg-surface2/50 p-1">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setTab(item.key)}
            className={`flex-1 rounded-lg px-1 py-2 text-[12px] ${
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
              <div className="mb-1 text-[12px] uppercase tracking-wide text-ink3">Оперативное состояние</div>
              <StateControls asset={asset} onChanged={(next) => setAsset(next)} />
            </div>
          ) : null}

          <div className="flex flex-wrap gap-2 pt-1">
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
                className={confirmDelete ? 'btn-danger h-10 px-3 text-[13px]' : 'btn-ghost h-10 px-3 text-[13px]'}
                onClick={async () => {
                  if (!confirmDelete) {
                    setConfirmDelete(true)
                    return
                  }
                  await gisApi.remove(asset.id)
                  window.location.reload()
                }}
              >
                {confirmDelete ? 'Точно удалить?' : 'Удалить'}
              </button>
            ) : null}
          </div>
        </>
      ) : null}

      {tab === 'photos' ? <PhotosTab assetId={asset.id} assetCode={asset.code} /> : null}
      {tab === 'docs' ? <DocumentsTab assetId={asset.id} canManage={canManageDocs} /> : null}
      {tab === 'history' ? <HistoryTab assetId={asset.id} /> : null}

      {showChildren ? (
        <ChildrenModal
          parentId={asset.id}
          title={`Состав: ${asset.name}`}
          children={children}
          canSwitch={canSwitch}
          onClose={() => setShowChildren(false)}
          onChanged={(updated) =>
            setChildren((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
          }
        />
      ) : null}

      <QrModal
        open={showQr}
        asset={{ id: asset.id, code: asset.code, name: asset.name }}
        onClose={() => setShowQr(false)}
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
