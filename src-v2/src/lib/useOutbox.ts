import { useCallback, useEffect, useState } from 'react'
import { countOps } from '../lib/outbox'
import { registerBackgroundSync, syncOutbox } from '../lib/sync'

/** Состояние офлайн-очереди: сколько ждёт, есть ли сеть, синхронизация. */
export function useOutbox() {
  const [pending, setPending] = useState(0)
  const [online, setOnline] = useState(() => (typeof navigator === 'undefined' ? true : navigator.onLine))
  const [syncing, setSyncing] = useState(false)
  const [lastResult, setLastResult] = useState<string | null>(null)
  const [conflicts, setConflicts] = useState(0)

  const refresh = useCallback(async () => {
    try {
      setPending(await countOps())
    } catch {
      setPending(0)
    }
  }, [])

  const sync = useCallback(async () => {
    setSyncing(true)
    try {
      const result = await syncOutbox()
      await refresh()
      setConflicts((prev) => prev + result.conflicts)
      if (result.sent || result.failed) {
        setLastResult(
          `Отправлено: ${result.sent}` +
            (result.failed ? `, ошибок: ${result.failed}` : '') +
            (result.conflicts ? `, конфликтов: ${result.conflicts}` : ''),
        )
      }
      return result
    } finally {
      setSyncing(false)
    }
  }, [refresh])

  useEffect(() => {
    void refresh()
    const onOnline = () => {
      setOnline(true)
      void sync().then(() => registerBackgroundSync())
    }
    const onOffline = () => setOnline(false)
    const onSwMessage = (event: MessageEvent) => {
      if (event.data?.type === 'karier-sync-request') void sync()
    }
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    navigator.serviceWorker?.addEventListener('message', onSwMessage)

    const timer = window.setInterval(() => {
      void countOps().then((count) => {
        setPending(count)
        if (count > 0 && navigator.onLine) {
          void sync().then(() => registerBackgroundSync())
        }
      })
    }, 15000)

    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
      navigator.serviceWorker?.removeEventListener('message', onSwMessage)
      window.clearInterval(timer)
    }
  }, [refresh, sync])

  return { pending, online, syncing, lastResult, conflicts, sync, refresh }
}
