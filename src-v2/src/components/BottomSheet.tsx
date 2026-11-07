import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, ReactNode } from 'react'

interface BottomSheetProps {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
}

type Snap = 'peek' | 'half' | 'full'

const HEIGHTS: Record<Snap, string> = {
  peek: '25dvh',
  half: '52dvh',
  full: '90dvh',
}

const ORDER: Snap[] = ['peek', 'half', 'full']

/**
 * Шторка снизу с тремя точками фиксации:
 * peek (25% — название и статус), half (52% — характеристики), full (90% — все вкладки).
 * Свайп вниз из peek закрывает карточку, из остальных — опускает на шаг.
 */
export function BottomSheet({ open, onClose, title, children }: BottomSheetProps) {
  const [snap, setSnap] = useState<Snap>('half')
  const startY = useRef<number | null>(null)
  const [dragOffset, setDragOffset] = useState(0)

  useEffect(() => {
    if (!open) {
      setSnap('half')
      setDragOffset(0)
    }
  }, [open])

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    startY.current = event.clientY
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (startY.current === null) return
    setDragOffset(event.clientY - startY.current)
  }

  const onPointerUp = () => {
    if (startY.current === null) return
    const delta = dragOffset
    startY.current = null
    setDragOffset(0)

    if (delta > 90) {
      const index = ORDER.indexOf(snap)
      if (index === 0) onClose()
      else setSnap(ORDER[index - 1])
      return
    }
    if (delta < -80) {
      const index = ORDER.indexOf(snap)
      setSnap(ORDER[Math.min(index + 1, ORDER.length - 1)])
    }
  }

  const expandToFull = () => setSnap((prev) => (prev === 'full' ? 'half' : 'full'))

  return (
    <>
      {open ? (
        <div className="fixed inset-0 z-[1100] bg-black/40 transition-opacity" onClick={onClose} aria-hidden />
      ) : null}

      <section
        className={`fixed inset-x-0 bottom-0 z-[1200] flex flex-col rounded-t-2xl border-t border-line bg-surface1 shadow-sheet transition-[height,transform] duration-200 md:max-w-xl md:left-1/2 md:-translate-x-1/2 ${
          open ? 'translate-y-0' : 'translate-y-full'
        }`}
        style={{
          height: HEIGHTS[snap],
          transform: dragOffset > 0 ? `translateY(${dragOffset}px)` : undefined,
          paddingBottom: 'env(safe-area-inset-bottom)',
        }}
        role="dialog"
        aria-modal="true"
        aria-label={title ?? 'Карточка объекта'}
      >
        <div
          className="flex cursor-grab touch-none flex-col items-center pt-2"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onDoubleClick={expandToFull}
        >
          <div className="h-1.5 w-12 rounded-full bg-line" />
          <div className="mt-1 flex items-center gap-3 text-[11px] text-ink3">
            <button type="button" onClick={() => setSnap('peek')} className="px-2 py-1">
              свернуть
            </button>
            <span>·</span>
            <button type="button" onClick={expandToFull} className="px-2 py-1">
              {snap === 'full' ? 'на половину' : 'развернуть'}
            </button>
          </div>
          {title ? <div className="mt-0.5 px-4 text-[13px] font-medium text-ink2">{title}</div> : null}
        </div>

        <div className="mt-1 flex-1 overflow-y-auto overscroll-contain px-4 pb-6">{children}</div>
      </section>
    </>
  )
}
