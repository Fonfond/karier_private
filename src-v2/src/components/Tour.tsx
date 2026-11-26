import { useEffect, useMemo, useState } from 'react'

const KEY = 'karier-tour-done'

interface TourStep {
  selector: string
  title: string
  text: string
}

const STEPS: TourStep[] = [
  {
    selector: '[data-tour="dashboard"]',
    title: 'Дашборд',
    text: 'Сводка по карьеру: сколько объектов под напряжением, открытые дефекты, обходы и «кукушки».',
  },
  {
    selector: '[data-tour="map"]',
    title: 'Карта',
    text: 'Все объекты на подложке карьера. Нажмите на маркер — откроется карточка с питанием и документами.',
  },
  {
    selector: '[data-tour="schema"]',
    title: 'Схема',
    text: 'Однолинейная схема питания: переключитесь в режим «Схема» на карте, чтобы увидеть связи и порты.',
  },
  {
    selector: '[data-tour="inspections"]',
    title: 'Обходы',
    text: 'Мобильный обход: отмечайте объекты «норма/дефект» и снимайте фото — работает даже без сети.',
  },
]

function rectOf(selector: string): DOMRect | null {
  const element = document.querySelector(selector)
  if (!element) return null
  const rect = element.getBoundingClientRect()
  return rect.width ? rect : null
}

export function Tour() {
  const [step, setStep] = useState(() => (localStorage.getItem(KEY) === '1' ? -1 : 0))
  const [rect, setRect] = useState<DOMRect | null>(null)

  const current = useMemo(() => (step >= 0 ? STEPS[step] : null), [step])

  useEffect(() => {
    if (!current) return
    const update = () => setRect(rectOf(current.selector))
    update()
    window.addEventListener('resize', update)
    window.addEventListener('scroll', update, true)
    return () => {
      window.removeEventListener('resize', update)
      window.removeEventListener('scroll', update, true)
    }
  }, [current])

  if (!current) return null

  const finish = () => {
    localStorage.setItem(KEY, '1')
    setStep(-1)
  }

  const next = () => {
    if (step + 1 >= STEPS.length) finish()
    else setStep(step + 1)
  }

  return (
    <div className="pointer-events-none fixed inset-0 z-[2000]">
      {rect ? (
        <div
          className="absolute rounded-xl ring-2 ring-accent ring-offset-2 ring-offset-bg transition-all"
          style={{
            left: rect.left - 6,
            top: rect.top - 6,
            width: rect.width + 12,
            height: rect.height + 12,
          }}
        />
      ) : null}

      <div className="pointer-events-auto absolute inset-x-3 bottom-[calc(84px+env(safe-area-inset-bottom))] mx-auto max-h-[60dvh] max-w-md overflow-y-auto rounded-2xl border border-accent/50 bg-surface1 p-4 shadow-2xl sm:inset-x-auto sm:bottom-6 sm:right-6">
        <div className="mb-1 text-[11px] uppercase tracking-wide text-ink3">
          Знакомство · {step + 1} из {STEPS.length}
        </div>
        <div className="text-[16px] font-semibold">{current.title}</div>
        <p className="mt-1 text-[13px] text-ink2">{current.text}</p>
        <div className="mt-3 flex items-center gap-2">
          <button type="button" className="btn-primary h-9 px-4 text-[13px]" onClick={next}>
            {step + 1 === STEPS.length ? 'Готово' : 'Далее'}
          </button>
          <button type="button" className="btn-ghost h-9 px-3 text-[13px]" onClick={finish}>
            Пропустить
          </button>
        </div>
      </div>
    </div>
  )
}
