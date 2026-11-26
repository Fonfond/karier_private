import { useCallback, useEffect, useState } from 'react'

const KEY = 'karier-presentation'

/** Режим презентации: крупнее интерфейс, скрыты админские и технические детали. */
export function usePresentation() {
  const [enabled, setEnabled] = useState(() => localStorage.getItem(KEY) === '1')

  useEffect(() => {
    document.documentElement.classList.toggle('presentation', enabled)
    localStorage.setItem(KEY, enabled ? '1' : '0')
  }, [enabled])

  const toggle = useCallback(() => setEnabled((prev) => !prev), [])

  return { presentation: enabled, togglePresentation: toggle }
}
