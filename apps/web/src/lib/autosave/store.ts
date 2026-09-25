/**
 * The autosave engine.
 *
 * Every edit is written to IndexedDB immediately and pushed to the server on
 * a debounce. The top bar shows "Saved", "Saving…" or "Offline" from
 * `saveStatus` (SPEC §2, global chrome).
 *
 * A 409 from the server means another device got there first. The local copy
 * is kept and flagged, rather than silently overwritten — the History tab is
 * where the user resolves it.
 */

import { create } from 'zustand';

import { api, ApiError } from '@/lib/api/client';
import type { DocumentKind, WorkspaceDocument } from '@/lib/api/types';
import {
  clearFailure,
  deleteDocument,
  documentKey,
  listDirtyDocuments,
  readDocument,
  recordFailure,
  writeDocument,
  type LocalDocument,
} from './db';

export type SaveStatus = 'saved' | 'saving' | 'offline' | 'error' | 'conflict';

/** How long to wait after the last edit before pushing. */
export const AUTOSAVE_DEBOUNCE_MS = 800;

interface AutosaveState {
  status: SaveStatus;
  pendingCount: number;
  lastSavedAt: number | null;
  lastError: string | null;
  setStatus: (status: SaveStatus, error?: string | null) => void;
  setPendingCount: (count: number) => void;
  markSaved: () => void;
}

export const useAutosaveStore = create<AutosaveState>((set) => ({
  status: 'saved',
  pendingCount: 0,
  lastSavedAt: null,
  lastError: null,
  setStatus: (status, error = null) => {
    set({ status, lastError: error });
  },
  setPendingCount: (pendingCount) => {
    set({ pendingCount });
  },
  markSaved: () => {
    set({ status: 'saved', lastSavedAt: Date.now(), lastError: null, pendingCount: 0 });
  },
}));

/** A short label for the History tab and the server's `device_label`. */
export function deviceLabel(): string {
  if (typeof navigator === 'undefined') return 'Unknown device';
  const ua = navigator.userAgent;
  const browser = /Firefox\//.test(ua)
    ? 'Firefox'
    : /Edg\//.test(ua)
      ? 'Edge'
      : /Chrome\//.test(ua)
        ? 'Chrome'
        : /Safari\//.test(ua)
          ? 'Safari'
          : 'Browser';
  const platform = /Windows/.test(ua)
    ? 'Windows'
    : /Mac OS X/.test(ua)
      ? 'macOS'
      : /Android/.test(ua)
        ? 'Android'
        : /Linux/.test(ua)
          ? 'Linux'
          : 'Unknown';
  return `${browser} on ${platform}`;
}

const timers = new Map<string, ReturnType<typeof setTimeout>>();

function isOffline(): boolean {
  return typeof navigator !== 'undefined' && navigator.onLine === false;
}

async function refreshPendingCount(): Promise<void> {
  const dirty = await listDirtyDocuments();
  useAutosaveStore.getState().setPendingCount(dirty.length);
}

/**
 * Push one document to the server.
 *
 * Returns the server's copy on success, or `null` when the push was deferred
 * (offline) or rejected as a conflict.
 */
export async function pushDocument(key: string): Promise<WorkspaceDocument | null> {
  const [kind, ...rest] = key.split(':');
  const scopeKey = rest.join(':');
  const local = await readDocument(kind as DocumentKind, scopeKey);
  if (!local || !local.dirty) return null;

  const store = useAutosaveStore.getState();

  if (isOffline()) {
    store.setStatus('offline');
    return null;
  }

  store.setStatus('saving');

  try {
    const saved = await api.put<WorkspaceDocument>('/workspace/documents', {
      kind: local.kind,
      scope_key: local.scopeKey,
      data: local.data,
      base_revision: local.revision,
      device_label: deviceLabel(),
    });

    await writeDocument({ ...local, revision: saved.revision, dirty: false });
    await clearFailure(key);
    await refreshPendingCount();
    useAutosaveStore.getState().markSaved();
    return saved;
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Save failed.';
    await recordFailure(key, message);
    await refreshPendingCount();

    if (error instanceof ApiError && error.status === 409) {
      // Another device changed this document. Keep the local edit; the user
      // decides in the History tab.
      useAutosaveStore.getState().setStatus('conflict', message);
      return null;
    }
    if (error instanceof ApiError && error.status === 401) {
      // The session ended; the client's refresh path already handles it.
      useAutosaveStore.getState().setStatus('error', message);
      return null;
    }

    useAutosaveStore.getState().setStatus(isOffline() ? 'offline' : 'error', message);
    return null;
  }
}

/**
 * Record an edit: write locally now, push after the debounce.
 *
 * Callers do not await the push — the UI must never block on the network.
 */
export async function saveDocument<T extends Record<string, unknown>>(
  kind: DocumentKind,
  scopeKey: string,
  data: T,
): Promise<void> {
  const key = documentKey(kind, scopeKey);
  const existing = await readDocument<T>(kind, scopeKey);

  await writeDocument<T>({
    key,
    kind,
    scopeKey,
    data,
    revision: existing?.revision ?? 0,
    dirty: true,
    updatedAt: Date.now(),
  });

  await refreshPendingCount();
  useAutosaveStore.getState().setStatus(isOffline() ? 'offline' : 'saving');

  const existingTimer = timers.get(key);
  if (existingTimer) clearTimeout(existingTimer);

  timers.set(
    key,
    setTimeout(() => {
      timers.delete(key);
      void pushDocument(key);
    }, AUTOSAVE_DEBOUNCE_MS),
  );
}

/** Read a document, preferring the local copy. */
export async function loadDocument<T extends Record<string, unknown>>(
  kind: DocumentKind,
  scopeKey: string,
): Promise<T | null> {
  const local = await readDocument<T>(kind, scopeKey);
  if (local) return local.data;

  try {
    const remote = await api.get<WorkspaceDocument<T>>(
      `/workspace/document?kind=${encodeURIComponent(kind)}&scope_key=${encodeURIComponent(scopeKey)}`,
    );
    await writeDocument<T>({
      key: documentKey(kind, scopeKey),
      kind,
      scopeKey,
      data: remote.data,
      revision: remote.revision,
      dirty: false,
      updatedAt: Date.parse(remote.updated_at),
    });
    return remote.data;
  } catch (error) {
    // A document that does not exist yet is not an error.
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function forgetDocument(kind: DocumentKind, scopeKey: string): Promise<void> {
  await deleteDocument(kind, scopeKey);
  await refreshPendingCount();
}

/** Push everything still dirty. Runs on reconnect and at startup. */
export async function flushPending(): Promise<void> {
  if (isOffline()) {
    useAutosaveStore.getState().setStatus('offline');
    return;
  }
  const dirty = await listDirtyDocuments();
  for (const entry of dirty) {
    await pushDocument(entry.key);
  }
  if (dirty.length === 0) useAutosaveStore.getState().markSaved();
}

/** Push immediately, skipping the debounce. Used before signing out. */
export async function flushNow(kind: DocumentKind, scopeKey: string): Promise<void> {
  const key = documentKey(kind, scopeKey);
  const timer = timers.get(key);
  if (timer) {
    clearTimeout(timer);
    timers.delete(key);
  }
  await pushDocument(key);
}

/** Wire up online/offline handling. Returns a cleanup function. */
export function startAutosave(): () => void {
  const handleOnline = () => {
    void flushPending();
  };
  const handleOffline = () => {
    useAutosaveStore.getState().setStatus('offline');
  };

  window.addEventListener('online', handleOnline);
  window.addEventListener('offline', handleOffline);
  if (isOffline()) handleOffline();
  void flushPending();

  return () => {
    window.removeEventListener('online', handleOnline);
    window.removeEventListener('offline', handleOffline);
    for (const timer of timers.values()) clearTimeout(timer);
    timers.clear();
  };
}

export type { LocalDocument };
