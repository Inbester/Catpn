import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IDBFactory } from 'fake-indexeddb';

import { ApiError } from '@/lib/api/client';
import * as client from '@/lib/api/client';
import { readDocument, resetDatabase } from './db';
import {
  AUTOSAVE_DEBOUNCE_MS,
  deviceLabel,
  flushNow,
  flushPending,
  loadDocument,
  pushDocument,
  saveDocument,
  useAutosaveStore,
} from './store';

function serverDocument(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'doc-1',
    kind: 'chart',
    scope_key: 'BTCUSDT:15m',
    data: { drawings: [] },
    revision: 1,
    device_label: 'Chrome on Linux',
    updated_at: '2026-09-25T12:00:00Z',
    ...overrides,
  };
}

describe('autosave', () => {
  beforeEach(() => {
    // A fresh IndexedDB per test so revisions never leak between cases.
    globalThis.indexedDB = new IDBFactory();
    resetDatabase();
    useAutosaveStore.setState({
      status: 'saved',
      pendingCount: 0,
      lastSavedAt: null,
      lastError: null,
    });
    vi.restoreAllMocks();
    // Only the debounce timer is faked. fake-indexeddb drives its request
    // events through the other timer APIs, and faking those deadlocks it.
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('writes locally before the network is touched', async () => {
    const put = vi.spyOn(client.api, 'put');

    await saveDocument('chart', 'BTCUSDT:15m', { drawings: ['a'] });

    const local = await readDocument('chart', 'BTCUSDT:15m');
    expect(local?.data).toEqual({ drawings: ['a'] });
    expect(local?.dirty).toBe(true);
    // Nothing is sent until the debounce elapses.
    expect(put).not.toHaveBeenCalled();
    expect(useAutosaveStore.getState().status).toBe('saving');
  });

  it('pushes to the server after the debounce and marks the document clean', async () => {
    const put = vi.spyOn(client.api, 'put').mockResolvedValue(serverDocument());

    await saveDocument('chart', 'BTCUSDT:15m', { drawings: ['a'] });
    await flushNow('chart', 'BTCUSDT:15m');

    expect(put).toHaveBeenCalledTimes(1);
    expect(put.mock.calls[0]?.[1]).toMatchObject({
      kind: 'chart',
      scope_key: 'BTCUSDT:15m',
      base_revision: 0,
    });

    const local = await readDocument('chart', 'BTCUSDT:15m');
    expect(local?.dirty).toBe(false);
    expect(local?.revision).toBe(1);
    expect(useAutosaveStore.getState().status).toBe('saved');
  });

  it('coalesces rapid edits into one push', async () => {
    const put = vi.spyOn(client.api, 'put').mockResolvedValue(serverDocument());

    await saveDocument('chart', 'BTCUSDT:15m', { v: 1 });
    await saveDocument('chart', 'BTCUSDT:15m', { v: 2 });
    await saveDocument('chart', 'BTCUSDT:15m', { v: 3 });
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS + 10);

    expect(put).toHaveBeenCalledTimes(1);
    expect(put.mock.calls[0]?.[1]).toMatchObject({ data: { v: 3 } });
  });

  it('sends the confirmed revision as base_revision on the next edit', async () => {
    const put = vi.spyOn(client.api, 'put').mockResolvedValue(serverDocument({ revision: 1 }));

    await saveDocument('chart', 'BTCUSDT:15m', { v: 1 });
    await flushNow('chart', 'BTCUSDT:15m');

    put.mockResolvedValue(serverDocument({ revision: 2 }));
    await saveDocument('chart', 'BTCUSDT:15m', { v: 2 });
    await flushNow('chart', 'BTCUSDT:15m');

    expect(put.mock.calls[1]?.[1]).toMatchObject({ base_revision: 1 });
  });

  it('keeps the local edit and flags a conflict on 409', async () => {
    vi.spyOn(client.api, 'put').mockRejectedValue(
      new ApiError(409, 'Document changed on the server.'),
    );

    await saveDocument('chart', 'BTCUSDT:15m', { v: 'mine' });
    await flushNow('chart', 'BTCUSDT:15m');

    expect(useAutosaveStore.getState().status).toBe('conflict');
    const local = await readDocument('chart', 'BTCUSDT:15m');
    // The user's work must survive for the History tab to resolve.
    expect(local?.data).toEqual({ v: 'mine' });
    expect(local?.dirty).toBe(true);
  });

  it('reports an error and keeps the document dirty when the push fails', async () => {
    vi.spyOn(client.api, 'put').mockRejectedValue(new ApiError(500, 'Internal server error.'));

    await saveDocument('chart', 'BTCUSDT:15m', { v: 1 });
    await flushNow('chart', 'BTCUSDT:15m');

    expect(useAutosaveStore.getState().status).toBe('error');
    expect((await readDocument('chart', 'BTCUSDT:15m'))?.dirty).toBe(true);
  });

  it('defers the push while offline', async () => {
    const put = vi.spyOn(client.api, 'put');
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);

    await saveDocument('chart', 'BTCUSDT:15m', { v: 1 });
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS + 10);

    expect(put).not.toHaveBeenCalled();
    expect(useAutosaveStore.getState().status).toBe('offline');
    expect((await readDocument('chart', 'BTCUSDT:15m'))?.dirty).toBe(true);
  });

  it('flushes everything still dirty once back online', async () => {
    const onLine = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    await saveDocument('chart', 'BTCUSDT:15m', { v: 1 });
    await saveDocument('chart', 'ETHUSDT:1h', { v: 2 });
    await vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS + 10);

    const put = vi.spyOn(client.api, 'put').mockResolvedValue(serverDocument());
    onLine.mockReturnValue(true);
    await flushPending();

    expect(put).toHaveBeenCalledTimes(2);
    expect((await readDocument('chart', 'BTCUSDT:15m'))?.dirty).toBe(false);
    expect((await readDocument('chart', 'ETHUSDT:1h'))?.dirty).toBe(false);
  });

  it('tracks how many documents are waiting to sync', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);

    await saveDocument('chart', 'BTCUSDT:15m', { v: 1 });
    expect(useAutosaveStore.getState().pendingCount).toBe(1);

    await saveDocument('settings', 'default', { v: 2 });
    expect(useAutosaveStore.getState().pendingCount).toBe(2);
  });

  it('pushing a clean document is a no-op', async () => {
    const put = vi.spyOn(client.api, 'put').mockResolvedValue(serverDocument());
    await saveDocument('chart', 'BTCUSDT:15m', { v: 1 });
    await flushNow('chart', 'BTCUSDT:15m');
    put.mockClear();

    await pushDocument('chart:BTCUSDT:15m');
    expect(put).not.toHaveBeenCalled();
  });
});

describe('loadDocument', () => {
  beforeEach(() => {
    globalThis.indexedDB = new IDBFactory();
    resetDatabase();
    vi.restoreAllMocks();
  });

  it('prefers the local copy without hitting the network', async () => {
    const put = vi.spyOn(client.api, 'put').mockResolvedValue(serverDocument());
    const get = vi.spyOn(client.api, 'get');

    await saveDocument('chart', 'BTCUSDT:15m', { v: 'local' });
    const loaded = await loadDocument('chart', 'BTCUSDT:15m');

    expect(loaded).toEqual({ v: 'local' });
    expect(get).not.toHaveBeenCalled();
    put.mockClear();
  });

  it('falls back to the server and caches the result', async () => {
    const get = vi
      .spyOn(client.api, 'get')
      .mockResolvedValue(serverDocument({ data: { v: 'remote' }, revision: 7 }));

    const loaded = await loadDocument('chart', 'BTCUSDT:15m');

    expect(loaded).toEqual({ v: 'remote' });
    expect(get).toHaveBeenCalledTimes(1);
    const cached = await readDocument('chart', 'BTCUSDT:15m');
    expect(cached?.revision).toBe(7);
    expect(cached?.dirty).toBe(false);
  });

  it('returns null for a document that does not exist yet', async () => {
    vi.spyOn(client.api, 'get').mockRejectedValue(new ApiError(404, 'No such document.'));
    expect(await loadDocument('chart', 'NEW:1m')).toBeNull();
  });

  it('propagates unexpected errors', async () => {
    vi.spyOn(client.api, 'get').mockRejectedValue(new ApiError(500, 'Boom.'));
    await expect(loadDocument('chart', 'NEW:1m')).rejects.toThrow('Boom.');
  });
});

describe('deviceLabel', () => {
  it('produces a readable browser and platform label', () => {
    expect(deviceLabel()).toMatch(/ on /);
  });
});
