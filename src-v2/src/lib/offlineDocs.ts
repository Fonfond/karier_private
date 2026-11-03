/** Офлайн-кэш документов: метаданные и файлы в IndexedDB. */

const DB_NAME = 'karier-offline'
const STORE = 'documents'
const VERSION = 1

export interface CachedDoc {
  id: string
  assetId: string
  title: string
  fileName: string
  mime: string
  savedAt: string
  size: number
  blob: Blob
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: 'id' })
        store.createIndex('assetId', 'assetId', { unique: false })
      }
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

export async function saveDocOffline(doc: {
  id: string
  assetId: string
  title: string
  fileName: string
  mime: string
  contentUrl: string
}): Promise<CachedDoc> {
  const response = await fetch(doc.contentUrl)
  if (!response.ok) throw new Error(`Не удалось скачать файл: ${response.status}`)
  const blob = await response.blob()
  const record: CachedDoc = {
    id: doc.id,
    assetId: doc.assetId,
    title: doc.title,
    fileName: doc.fileName,
    mime: doc.mime,
    savedAt: new Date().toISOString(),
    size: blob.size,
    blob,
  }
  const db = await openDb()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).put(record)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
  db.close()
  return record
}

export async function getDocOffline(id: string): Promise<CachedDoc | null> {
  const db = await openDb()
  const record = await new Promise<CachedDoc | null>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly')
    const request = tx.objectStore(STORE).get(id)
    request.onsuccess = () => resolve((request.result as CachedDoc) ?? null)
    request.onerror = () => reject(request.error)
  })
  db.close()
  return record
}

export async function listOfflineDocs(assetId?: string): Promise<CachedDoc[]> {
  const db = await openDb()
  const records = await new Promise<CachedDoc[]>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly')
    const store = tx.objectStore(STORE)
    const request = assetId ? store.index('assetId').getAll(assetId) : store.getAll()
    request.onsuccess = () => resolve(request.result as CachedDoc[])
    request.onerror = () => reject(request.error)
  })
  db.close()
  return records
}

export async function removeOfflineDoc(id: string): Promise<void> {
  const db = await openDb()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).delete(id)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
  db.close()
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} КБ`
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`
}
