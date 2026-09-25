/**
 * IndexedDB store backing the autosave framework.
 *
 * SPEC/DECISIONS: storage is local-first. Every edit lands here first, so it
 * survives a refresh, a crash or going offline, and is pushed to the server
 * in the background. Jobs later checkpoint into the same database.
 */

import type { DocumentKind } from '@/lib/api/types';

const DB_NAME = 'quanta';
const DB_VERSION = 1;
const STORE_DOCUMENTS = 'documents';
const STORE_QUEUE = 'sync-queue';

export interface LocalDocument<T = Record<string, unknown>> {
  /** `${kind}:${scopeKey}` — the primary key. */
  key: string;
  kind: DocumentKind;
  scopeKey: string;
  data: T;
  /** Last revision confirmed by the server; 0 until the first successful push. */
  revision: number;
  /** True while there are local edits the server has not accepted. */
  dirty: boolean;
  updatedAt: number;
}

export interface QueueEntry {
  key: string;
  attempts: number;
  lastError: string | null;
  queuedAt: number;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDatabase(): Promise<IDBDatabase> {
  dbPromise ??= new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_DOCUMENTS)) {
        const store = db.createObjectStore(STORE_DOCUMENTS, { keyPath: 'key' });
        store.createIndex('kind', 'kind', { unique: false });
        store.createIndex('dirty', 'dirty', { unique: false });
      }
      if (!db.objectStoreNames.contains(STORE_QUEUE)) {
        db.createObjectStore(STORE_QUEUE, { keyPath: 'key' });
      }
    };

    request.onsuccess = () => {
      resolve(request.result);
    };
    request.onerror = () => {
      reject(request.error ?? new Error('Could not open the local database.'));
    };
  });
  return dbPromise;
}

/** Reset the cached handle. Used by tests. */
export function resetDatabase(): void {
  dbPromise = null;
}

function promisify<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => {
      resolve(request.result);
    };
    request.onerror = () => {
      reject(request.error ?? new Error('IndexedDB request failed.'));
    };
  });
}

export function documentKey(kind: DocumentKind, scopeKey: string): string {
  return `${kind}:${scopeKey}`;
}

export async function readDocument<T>(
  kind: DocumentKind,
  scopeKey: string,
): Promise<LocalDocument<T> | undefined> {
  const db = await openDatabase();
  const tx = db.transaction(STORE_DOCUMENTS, 'readonly');
  const result = await promisify<LocalDocument<T> | undefined>(
    tx.objectStore(STORE_DOCUMENTS).get(documentKey(kind, scopeKey)) as IDBRequest<
      LocalDocument<T> | undefined
    >,
  );
  return result;
}

export async function writeDocument<T>(document: LocalDocument<T>): Promise<void> {
  const db = await openDatabase();
  const tx = db.transaction(STORE_DOCUMENTS, 'readwrite');
  await promisify(tx.objectStore(STORE_DOCUMENTS).put(document));
}

export async function listDirtyDocuments(): Promise<LocalDocument[]> {
  const db = await openDatabase();
  const tx = db.transaction(STORE_DOCUMENTS, 'readonly');
  const all = await promisify<LocalDocument[]>(
    tx.objectStore(STORE_DOCUMENTS).getAll() as IDBRequest<LocalDocument[]>,
  );
  return all.filter((entry) => entry.dirty);
}

export async function listDocuments(): Promise<LocalDocument[]> {
  const db = await openDatabase();
  const tx = db.transaction(STORE_DOCUMENTS, 'readonly');
  return promisify<LocalDocument[]>(
    tx.objectStore(STORE_DOCUMENTS).getAll() as IDBRequest<LocalDocument[]>,
  );
}

export async function deleteDocument(kind: DocumentKind, scopeKey: string): Promise<void> {
  const db = await openDatabase();
  const tx = db.transaction(STORE_DOCUMENTS, 'readwrite');
  await promisify(tx.objectStore(STORE_DOCUMENTS).delete(documentKey(kind, scopeKey)));
}

export async function recordFailure(key: string, error: string): Promise<void> {
  const db = await openDatabase();
  const tx = db.transaction(STORE_QUEUE, 'readwrite');
  const store = tx.objectStore(STORE_QUEUE);
  const existing = await promisify<QueueEntry | undefined>(
    store.get(key) as IDBRequest<QueueEntry | undefined>,
  );
  await promisify(
    store.put({
      key,
      attempts: (existing?.attempts ?? 0) + 1,
      lastError: error,
      queuedAt: existing?.queuedAt ?? Date.now(),
    } satisfies QueueEntry),
  );
}

export async function clearFailure(key: string): Promise<void> {
  const db = await openDatabase();
  const tx = db.transaction(STORE_QUEUE, 'readwrite');
  await promisify(tx.objectStore(STORE_QUEUE).delete(key));
}
