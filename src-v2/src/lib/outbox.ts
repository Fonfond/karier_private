/** Офлайн-очередь: обходы, дефекты и фото уходят на сервер при появлении сети. */

import { openDB, type IDBPDatabase } from 'idb'

export type OpKind = 'inspection_create' | 'inspection_item' | 'inspection_submit' | 'defect' | 'media'

export interface OutboxOp {
  id: string
  kind: OpKind
  payload: Record<string, unknown>
  createdAt: string
  attempts: number
  lastError?: string
}

const DB_NAME = 'karier-outbox'
const VERSION = 1
const OPS = 'ops'
const BLOBS = 'blobs'
const IDMAP = 'idmap'

let dbPromise: Promise<IDBPDatabase> | null = null

function db(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, VERSION, {
      upgrade(database) {
        if (!database.objectStoreNames.contains(OPS)) {
          const store = database.createObjectStore(OPS, { keyPath: 'id' })
          store.createIndex('createdAt', 'createdAt')
        }
        if (!database.objectStoreNames.contains(BLOBS)) {
          database.createObjectStore(BLOBS)
        }
        if (!database.objectStoreNames.contains(IDMAP)) {
          database.createObjectStore(IDMAP)
        }
      },
    })
  }
  return dbPromise
}

export function newId(): string {
  return crypto.randomUUID()
}

export async function enqueue(kind: OpKind, payload: Record<string, unknown>, blob?: Blob): Promise<string> {
  const id = newId()
  const op: OutboxOp = {
    id,
    kind,
    payload,
    createdAt: new Date().toISOString(),
    attempts: 0,
  }
  const database = await db()
  await database.put(OPS, op)
  if (blob) await database.put(BLOBS, blob, id)
  return id
}

export async function listOps(): Promise<OutboxOp[]> {
  const database = await db()
  const ops = (await database.getAll(OPS)) as OutboxOp[]
  return ops.sort((a, b) => a.createdAt.localeCompare(b.createdAt))
}

export async function countOps(): Promise<number> {
  const database = await db()
  return database.count(OPS)
}

export async function getBlob(id: string): Promise<Blob | undefined> {
  const database = await db()
  return database.get(BLOBS, id)
}

export async function removeOp(id: string): Promise<void> {
  const database = await db()
  await database.delete(OPS, id)
  await database.delete(BLOBS, id)
}

export async function markFailed(id: string, error: string): Promise<void> {
  const database = await db()
  const op = (await database.get(OPS, id)) as OutboxOp | undefined
  if (!op) return
  op.attempts += 1
  op.lastError = error.slice(0, 300)
  await database.put(OPS, op)
}

export async function mapId(tempId: string, realId: string): Promise<void> {
  const database = await db()
  await database.put(IDMAP, realId, tempId)
}

export async function resolveId(tempId: string): Promise<string> {
  const database = await db()
  return ((await database.get(IDMAP, tempId)) as string | undefined) ?? tempId
}

export async function clearOutbox(): Promise<void> {
  const database = await db()
  await database.clear(OPS)
  await database.clear(BLOBS)
  await database.clear(IDMAP)
}
