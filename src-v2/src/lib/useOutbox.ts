import { useCallback, useEffect, useState } from 'react'
import { countOps } from '../lib/outbox'
import { syncOutbox } from '../lib/sync'

/** Состояние офлайн-очереди: сколько ждёт, есть ли сеть, синхронизация. */
export function useOutbox() {
  const [pending, setPending] = useState(0)
  const [online, setOnline] = useState(() => (typeof navigator === 'undefined' ? true : navigator.onLine))
  const [syncing, setSyncing] = useState(false)
  const [lastResult, setLastResult] = useState<string | null>(null)

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
      if (result.sent || result.failed) {
        setLastResult(
          `Отправлено: ${result.sent}` + (result.failed ? `, ошибок: ${result.failed}` : ''),
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
      void sync()
    }
    const onOffline = () => setOnline(false)
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    const timer = window.setInterval(() => {
      void countOps().then((count) => {
        setPending(count)
        if (count > 0 && navigator.onLine) void sync()
      })
    }, 20000)
    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
      window.clearInterval(timer)
    }
  }, [refresh, sync])

  return { pending, online, syncing, lastResult, sync, refresh }
}
