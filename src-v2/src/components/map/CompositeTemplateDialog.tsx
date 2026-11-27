import { useEffect, useMemo, useState } from 'react'
import { Alert } from '../ui'
import { ApiError } from '../../lib/api'
import type { AssetType, CompositeCreateResult } from '../../lib/gis'
import { gisApi } from '../../lib/gis'
import {
  CELL_KIND_TITLES,
  MAX_CELLS_PER_SECTION,
  MIN_CELLS_PER_SECTION,
  PS_DEFAULT_CELLS,
  buildSectionPreview,
  previewTotals,
  templateForType,
  templateSummary,
  templateTitle,
  validateCellsPerSection,
  type CompositeTemplate,
} from '../../lib/equipmentTemplates'

interface Props {
  open: boolean
  /** Точка вставки на холсте схемы (пиксели React Flow). */
  center: { x: number; y: number }
  onClose: () => void
  onCreated: (result: CompositeCreateResult) => void
}

const PROFILE_ICON: Record<string, string> = {
  bkru: '▤',
  ps_35_6: '🏭',
  ktp: '⚡',
}

const PROFILE_ORDER: Record<string, number> = { bkru: 0, ps_35_6: 1, ktp: 2 }

interface Candidate {
  type: AssetType
  template: CompositeTemplate
}

/**
 * Мастер «По шаблону»: создание составного устройства одной транзакцией
 * (`POST /api/schema/composite`).
 *
 * БКРУ — ровно 6 ячеек; ПС 35/6 — по 17 ячеек на секцию (параметр 1…50);
 * КТП — без ячеек, только вводной разъединитель. Предпросмотр состава считается
 * той же логикой, что и на backend (`lib/equipmentTemplates.ts`), поэтому
 * оператор видит ровно то, что появится на схеме.
 */
export function CompositeTemplateDialog({ open, center, onClose, onCreated }: Props) {
  const [types, setTypes] = useState<AssetType[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState('')
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [cellsPerSection, setCellsPerSection] = useState(String(PS_DEFAULT_CELLS))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    gisApi
      .types()
      .then((list) => {
        if (cancelled) return
        setTypes(list)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Не удалось загрузить модели оборудования')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open])

  const candidates = useMemo<Candidate[]>(() => {
    return types
      .map((type) => ({ type, template: templateForType(type) }))
      .filter((item) => item.template.isV2 && (item.template.sections.length > 0 || item.template.disconnector))
      .sort((a, b) => {
        const order = (item: Candidate) =>
          PROFILE_ORDER[item.template.profile ?? ''] ?? 10
        return order(a) - order(b) || a.type.name.localeCompare(b.type.name, 'ru')
      })
  }, [types])

  const active = candidates.find((item) => item.type.code === selected) ?? candidates[0] ?? null
  const template = active?.template ?? null

  // Выбор по умолчанию: первое составное устройство (обычно БКРУ).
  useEffect(() => {
    if (!open) return
    if (candidates.length === 0) return
    if (candidates.some((item) => item.type.code === selected)) return
    const first = candidates[0]
    setSelected(first.type.code)
    setName(first.type.name)
    setCellsPerSection(String(first.template.cellsPerSection ?? PS_DEFAULT_CELLS))
  }, [open, candidates, selected])

  const perSectionError = template?.configurable ? validateCellsPerSection(cellsPerSection) : null
  const perSectionValue = Number(String(cellsPerSection).replace(',', '.'))
  const preview = template ? buildSectionPreview(template, template.configurable ? perSectionValue : null) : []
  const totals = template ? previewTotals(template, template.configurable ? perSectionValue : null) : null

  const pick = (candidate: Candidate) => {
    setSelected(candidate.type.code)
    setName(candidate.type.name)
    setCode('')
    setCellsPerSection(String(candidate.template.cellsPerSection ?? PS_DEFAULT_CELLS))
    setError(null)
  }

  const submit = async () => {
    if (!template || !active) return
    if (name.trim().length < 2) {
      setError('Название: минимум 2 символа')
      return
    }
    if (perSectionError) {
      setError(perSectionError)
      return
    }
    setBusy(true)
    setError(null)
    try {
      const result = await gisApi.createComposite({
        type_code: active.type.code,
        name: name.trim(),
        x: Math.round(center.x),
        y: Math.round(center.y),
        code: code.trim() || null,
        cells_per_section: template.configurable ? Math.trunc(perSectionValue) : null,
      })
      onCreated(result)
      onClose()
    } catch (err) {
      if (err instanceof ApiError) {
        const fieldText = Object.values(err.fields ?? {}).join('; ')
        setError(fieldText ? `${err.message} — ${fieldText}` : err.message)
      } else {
        setError('Не удалось создать устройство по шаблону')
      }
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[1500] flex items-end justify-center bg-black/60 p-3 sm:items-center">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="composite-dialog-title"
        className="card modal-safe flex max-h-[92vh] w-full max-w-xl flex-col p-4 text-[13px]"
      >
        <div className="mb-2 flex items-start justify-between gap-2">
          <div>
            <h2 id="composite-dialog-title" className="text-[15px] font-semibold">
              По шаблону
            </h2>
            <p className="text-[11px] text-ink3">
              Блок с секциями и ячейками создаётся одной транзакцией и сразу появляется на схеме.
            </p>
          </div>
          <button type="button" className="btn-ghost h-8 px-2" onClick={onClose} title="Закрыть" aria-label="Закрыть мастер">
            ✕
          </button>
        </div>

        {error ? (
          <div className="mb-2">
            <Alert kind="error">{error}</Alert>
          </div>
        ) : null}

        {loading ? <div className="p-2 text-[12px] text-ink3">Загружаем модели оборудования…</div> : null}

        {!loading && candidates.length === 0 ? (
          <div className="rounded-lg border border-warm/40 bg-warm/10 p-3 text-[12px] text-warm">
            В справочнике нет составных устройств (БКРУ, ПС 35/6, КТП). Проверьте модели оборудования
            и шаблон состава.
          </div>
        ) : null}

        {candidates.length > 0 ? (
          <>
            <div className="mb-2 grid gap-1.5 sm:grid-cols-3" role="radiogroup" aria-label="Шаблон устройства">
              {candidates.map((candidate) => {
                const isActive = candidate.type.code === active?.type.code
                return (
                  <button
                    key={candidate.type.code}
                    type="button"
                    role="radio"
                    aria-checked={isActive}
                    data-testid={`composite-template-${candidate.template.profile ?? candidate.type.code}`}
                    className={`rounded-xl border px-2.5 py-2 text-left transition ${
                      isActive
                        ? 'border-accent bg-accent/10 text-ink'
                        : 'border-line bg-surface2/50 text-ink2 hover:border-accent/60'
                    }`}
                    onClick={() => pick(candidate)}
                  >
                    <div className="flex items-center gap-1.5">
                      <span aria-hidden="true">
                        {PROFILE_ICON[candidate.template.profile ?? ''] ?? '▣'}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[12px] font-semibold">
                        {templateTitle(candidate.template, candidate.type.name)}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[10px] text-ink3">
                      {templateSummary(candidate.template, candidate.template.cellsPerSection)}
                    </div>
                    <div className="text-[10px] text-ink3">{candidate.type.name}</div>
                  </button>
                )
              })}
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              <label className="block text-[11px] text-ink3">
                Название
                <input
                  className="input mt-1 h-9 text-[13px]"
                  value={name}
                  maxLength={255}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="БКРУ-3 / ПС 35/6 «Северная»"
                  autoFocus
                />
              </label>
              <label className="block text-[11px] text-ink3">
                Код (необязательно)
                <input
                  className="input mt-1 h-9 font-mono text-[13px]"
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  placeholder="сгенерируется автоматически"
                />
              </label>
            </div>

            {template?.configurable ? (
              <div className="mt-2 rounded-xl border border-line bg-surface2/40 p-2">
                <label className="block text-[11px] text-ink3">
                  Ячеек на секцию (1…{MAX_CELLS_PER_SECTION})
                  <input
                    className="input mt-1 h-9 w-[120px] text-[13px]"
                    inputMode="numeric"
                    type="number"
                    min={MIN_CELLS_PER_SECTION}
                    max={MAX_CELLS_PER_SECTION}
                    step={1}
                    value={cellsPerSection}
                    aria-invalid={Boolean(perSectionError)}
                    onChange={(event) => setCellsPerSection(event.target.value)}
                  />
                </label>
                <p className={`mt-1 text-[11px] ${perSectionError ? 'text-bad' : 'text-ink3'}`}>
                  {perSectionError ?? `По умолчанию ${PS_DEFAULT_CELLS}; состав секции: вводная + отходящие + секционная.`}
                </p>
              </div>
            ) : null}

            {totals ? (
              <div className="mt-2 rounded-xl border border-line bg-surface2/30 p-2">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wide text-ink3">Состав</span>
                  <span className="rounded-full border border-accent/40 bg-accent/10 px-2 py-0.5 text-[11px] text-accent">
                    {totals.cells} ячеек
                    {totals.hasDisconnector ? ' + разъединитель' : ''}
                  </span>
                  <span className="text-[11px] text-ink3">
                    секций: {totals.sections} · всего элементов: {totals.children}
                  </span>
                </div>
                <div className="max-h-[22vh] space-y-1 overflow-y-auto">
                  {preview.map((section) => (
                    <div key={section.section_no} className="rounded-lg bg-surface1/70 px-2 py-1">
                      <div className="flex items-center justify-between gap-2 text-[11px]">
                        <span className="text-ink">{section.label}</span>
                        <span className="text-ink3">
                          {section.voltage_kv != null ? `${section.voltage_kv} кВ · ` : ''}
                          {section.total} ячеек
                        </span>
                      </div>
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        {section.cells
                          .filter((cell) => cell.count > 0)
                          .map((cell) => (
                            <span
                              key={cell.cell_kind}
                              className="rounded border border-line px-1.5 py-0.5 text-[10px] text-ink3"
                            >
                              {CELL_KIND_TITLES[cell.cell_kind]} × {cell.count}
                            </span>
                          ))}
                      </div>
                    </div>
                  ))}
                  {totals.hasDisconnector ? (
                    <div className="rounded-lg bg-surface1/70 px-2 py-1 text-[11px] text-ink2">
                      Вводной разъединитель (ячеек нет) — {CELL_KIND_TITLES.in}
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}

            <p className="mt-2 text-[11px] text-ink3">
              Точка вставки: X {Math.round(center.x)} · Y {Math.round(center.y)} px. Ячейки создаются
              отключёнными (зелёные); включение — кнопкой на схеме, в карточке или в списке.
            </p>
          </>
        ) : null}

        <div className="mt-3 flex justify-end gap-2">
          <button type="button" className="btn-ghost h-9 px-3" onClick={onClose}>
            Отмена
          </button>
          <button
            type="button"
            className="btn-primary h-9 px-4"
            data-testid="composite-create"
            disabled={busy || !template || name.trim().length < 2 || Boolean(perSectionError)}
            onClick={() => void submit()}
          >
            {busy ? 'Создаём…' : 'Создать по шаблону'}
          </button>
        </div>
      </div>
    </div>
  )
}
