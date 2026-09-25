import { describe, expect, it } from 'vitest';

import { applyBar } from './useKlines';
import type { Bar } from '../lib/types';

const bar = (time: number, close: number, closed = true): Bar => ({
  time,
  open: 100,
  high: 110,
  low: 90,
  close,
  volume: 10,
  closed,
});

const T = 1_700_000_000_000;
const MINUTE = 60_000;

describe('applyBar', () => {
  it('seeds an empty series', () => {
    expect(applyBar([], bar(T, 100))).toEqual([bar(T, 100)]);
  });

  it('replaces the forming bar in place', () => {
    const series = [bar(T, 100), bar(T + MINUTE, 101, false)];
    const next = applyBar(series, bar(T + MINUTE, 105, false));

    expect(next).toHaveLength(2);
    expect(next[1]?.close).toBe(105);
  });

  it('appends a newly opened bar', () => {
    const series = [bar(T, 100, false)];
    const next = applyBar(series, bar(T + MINUTE, 101, false));

    expect(next).toHaveLength(2);
    expect(next[1]?.time).toBe(T + MINUTE);
  });

  it('never reopens a closed bar', () => {
    // A late frame after a reconnect must not rewrite settled history —
    // the same rule the server enforces on write.
    const series = [bar(T, 100, true)];
    const next = applyBar(series, bar(T, 999, false));

    expect(next[0]?.close).toBe(100);
    expect(next[0]?.closed).toBe(true);
  });

  it('lets a closed bar confirm the forming one', () => {
    const series = [bar(T, 100, false)];
    const next = applyBar(series, bar(T, 104, true));

    expect(next[0]?.close).toBe(104);
    expect(next[0]?.closed).toBe(true);
  });

  it('corrects an earlier bar it already holds', () => {
    const series = [bar(T, 100), bar(T + MINUTE, 101), bar(T + 2 * MINUTE, 102)];
    const next = applyBar(series, bar(T + MINUTE, 150));

    expect(next[1]?.close).toBe(150);
    expect(next).toHaveLength(3);
  });

  it('ignores a bar older than anything it holds', () => {
    const series = [bar(T, 100), bar(T + MINUTE, 101)];
    const next = applyBar(series, bar(T - MINUTE, 99));

    expect(next).toEqual(series);
  });

  it('does not mutate the series it was given', () => {
    const series = [bar(T, 100, false)];
    const snapshot = structuredClone(series);
    applyBar(series, bar(T, 105, false));

    expect(series).toEqual(snapshot);
  });
});
