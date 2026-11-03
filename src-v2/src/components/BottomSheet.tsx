import { useEffect, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, ReactNode } from 'react'

interface BottomSheetProps {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
}

/**
 * Шторка снизу: два положения (peek ≈ 46vh и full ≈ 88vh).
 * Тянется за ручку, закрывается свайпом вниз или тапом по фону.
 */
export function BottomSheet({ open, onClose, title, children }: BottomSheetProps) {
  const [expanded, setExpanded] = useState(false)
  const startY = useRef<number | null>(null)
  const [dragOffset, setDragOffset] = useState(0)

  useEffect(() => {
    if (!open) {
      setExpanded(false)
      setDragOffset(0)
    }
  }, [open])

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    startY.current = event.clientY
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (startY.current === null) return
    const delta = event.clientY - startY.current
    setDragOffset(delta)
  }

  const onPointerUp = () => {
    if (startY.current === null) return
    const delta = dragOffset
    startY.current = null
    setDragOffset(0)
    if (delta < -50) setExpanded(true)
    else if (delta > 70) {
      if (expanded) setExpanded(false)
      else onClose()
    }
  }

  const height = expanded ? '88vh' : '46vh'

  return (
    <>
      {open ? (
        <div
          className="fixed inset-0 z-[1100] bg-black/40 transition-opacity"
          onClick={onClose}
          aria-hidden
        />
      ) : null}

      <section
        className={`fixed inset-x-0 bottom-0 z-[1200] flex flex-col rounded-t-2xl border-t border-line bg-surface1 shadow-sheet transition-transform duration-200 ${
          open ? 'translate-y-0' : 'translate-y-full'
        }`}
        style={{ height, transform: dragOffset > 0 ? `translateY(${dragOffset}px)` : undefined }}
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
        >
          <div className="h-1 w-10 rounded-full bg-line" />
          {title ? (
            <div className="mt-2 px-4 text-[13px] font-medium text-ink2">{title}</div>
          ) : null}
        </div>

        <div className="mt-2 flex-1 overflow-y-auto overscroll-contain px-4 pb-6">{children}</div>
      </section>
    </>
  )
}
