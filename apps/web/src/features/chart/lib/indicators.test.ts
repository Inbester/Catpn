import { describe, expect, it } from 'vitest';

import { atr, bollinger, ema, heikinAshi, macd, rsi, sma } from './indicators';
import type { Bar } from './types';

/** Round for comparison against hand-computed references. */
const round = (value: number | null, places = 4): number | null =>
  value === null ? null : Number(value.toFixed(places));

function makeBars(closes: number[]): Bar[] {
  return closes.map((close, i) => ({
    time: 1_700_000_000_000 + i * 60_000,
    open: close,
    high: close + 1,
    low: close - 1,
    close,
    volume: 100,
    closed: true,
  }));
}

describe('sma', () => {
  it('is null until the window is full', () => {
    expect(sma([1, 2, 3, 4], 3)).toEqual([null, null, 2, 3]);
  });

  it('matches a hand-computed average', () => {
    expect(sma([2, 4, 6, 8, 10], 5)).toEqual([null, null, null, null, 6]);
  });

  it('handles a length of one', () => {
    expect(sma([5, 7], 1)).toEqual([5, 7]);
  });

  it('returns all nulls when there is not enough data', () => {
    expect(sma([1, 2], 5)).toEqual([null, null]);
  });

  it('rejects a zero length', () => {
    expect(() => sma([1, 2, 3], 0)).toThrow(RangeError);
  });
});

describe('ema', () => {
  it('seeds from the SMA of the first window', () => {
    // SMA(1..5) = 3, so the first EMA value is 3.
    const result = ema([1, 2, 3, 4, 5], 5);
    expect(result.slice(0, 4)).toEqual([null, null, null, null]);
    expect(result[4]).toBe(3);
  });

  it('applies the standard smoothing factor', () => {
    // k = 2/(3+1) = 0.5. Seed = SMA(1,2,3) = 2.
    // next = 4*0.5 + 2*0.5 = 3; then 5*0.5 + 3*0.5 = 4.
    const result = ema([1, 2, 3, 4, 5], 3);
    expect(result).toEqual([null, null, 2, 3, 4]);
  });

  it('tracks a constant series exactly', () => {
    const result = ema(new Array<number>(20).fill(42), 10);
    expect(round(result[19] as number)).toBe(42);
  });

  it('reacts faster than the SMA of the same length', () => {
    const values = [...new Array<number>(20).fill(10), 20];
    const fastEma = ema(values, 10);
    const slowSma = sma(values, 10);
    expect(fastEma[20] as number).toBeGreaterThan(slowSma[20] as number);
  });
});

describe('rsi', () => {
  it('is 100 when every change is a gain', () => {
    const rising = Array.from({ length: 30 }, (_, i) => 100 + i);
    expect(round(rsi(rising, 14)[29] as number)).toBe(100);
  });

  it('is 0 when every change is a loss', () => {
    const falling = Array.from({ length: 30 }, (_, i) => 100 - i);
    expect(round(rsi(falling, 14)[29] as number)).toBe(0);
  });

  it('sits at 50 for a symmetric zigzag', () => {
    const zigzag = Array.from({ length: 60 }, (_, i) => 100 + (i % 2 === 0 ? 0 : 1));
    const value = rsi(zigzag, 14)[59] as number;
    expect(value).toBeGreaterThan(40);
    expect(value).toBeLessThan(60);
  });

  it('stays within 0 and 100 on noisy data', () => {
    const noisy = Array.from({ length: 200 }, (_, i) => 100 + Math.sin(i / 3) * 12 + (i % 7));
    for (const value of rsi(noisy, 14)) {
      if (value === null) continue;
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(100);
    }
  });

  it('has no value before the warm-up completes', () => {
    const result = rsi([1, 2, 3, 4, 5], 14);
    expect(result.every((v) => v === null)).toBe(true);
  });
});

describe('macd', () => {
  it('is zero for a flat series once warmed up', () => {
    const flat = new Array<number>(100).fill(50);
    const result = macd(flat);
    expect(round(result.macd[99] as number)).toBe(0);
    expect(round(result.signal[99] as number)).toBe(0);
    expect(round(result.histogram[99] as number)).toBe(0);
  });

  it('is positive while the fast average leads', () => {
    const rising = Array.from({ length: 120 }, (_, i) => 100 + i);
    expect(macd(rising).macd[119] as number).toBeGreaterThan(0);
  });

  it('is negative in a downtrend', () => {
    const falling = Array.from({ length: 120 }, (_, i) => 500 - i * 2);
    expect(macd(falling).macd[119] as number).toBeLessThan(0);
  });

  it('keeps histogram = macd - signal', () => {
    const values = Array.from({ length: 150 }, (_, i) => 100 + Math.sin(i / 8) * 20);
    const { macd: line, signal, histogram } = macd(values);
    for (let i = 0; i < values.length; i += 1) {
      if (histogram[i] === null) continue;
      expect(round(histogram[i] as number)).toBe(
        round((line[i] as number) - (signal[i] as number)),
      );
    }
  });

  it('has no signal before the slow average warms up', () => {
    const result = macd(new Array<number>(20).fill(10));
    expect(result.signal.every((v) => v === null)).toBe(true);
  });
});

describe('atr', () => {
  it('equals the range for a constant-range series', () => {
    // Each bar spans close-1 to close+1, so the true range is 2 once the
    // gap between closes is accounted for... on a flat series it is exactly 2.
    const bars = makeBars(new Array<number>(40).fill(100));
    expect(round(atr(bars, 14)[39] as number)).toBe(2);
  });

  it('grows when volatility grows', () => {
    const calm = makeBars(new Array<number>(40).fill(100));
    const wild = calm.map((bar, i) =>
      i > 20 ? { ...bar, high: bar.close + 10, low: bar.close - 10 } : bar,
    );
    expect(atr(wild, 14)[39] as number).toBeGreaterThan(atr(calm, 14)[39] as number);
  });

  it('is never negative', () => {
    const bars = makeBars(Array.from({ length: 100 }, (_, i) => 100 + Math.sin(i) * 5));
    for (const value of atr(bars, 14)) {
      if (value !== null) expect(value).toBeGreaterThanOrEqual(0);
    }
  });
});

describe('bollinger', () => {
  it('collapses onto the mean for a flat series', () => {
    const { middle, upper, lower } = bollinger(new Array<number>(40).fill(100), 20);
    expect(middle[39]).toBe(100);
    expect(round(upper[39] as number)).toBe(100);
    expect(round(lower[39] as number)).toBe(100);
  });

  it('keeps the bands symmetric around the mean', () => {
    const values = Array.from({ length: 60 }, (_, i) => 100 + Math.sin(i / 4) * 10);
    const { middle, upper, lower } = bollinger(values, 20);
    for (let i = 19; i < values.length; i += 1) {
      const mean = middle[i] as number;
      expect(round((upper[i] as number) - mean)).toBe(round(mean - (lower[i] as number)));
    }
  });

  it('widens with the multiplier', () => {
    const values = Array.from({ length: 60 }, (_, i) => 100 + Math.sin(i / 4) * 10);
    const narrow = bollinger(values, 20, 1);
    const wide = bollinger(values, 20, 3);
    expect(wide.upper[59] as number).toBeGreaterThan(narrow.upper[59] as number);
  });
});

describe('heikinAshi', () => {
  it('sets close to the average of the four prices', () => {
    const bars: Bar[] = [
      { time: 1, open: 10, high: 14, low: 8, close: 12, volume: 1, closed: true },
    ];
    const [ha] = heikinAshi(bars);
    expect(ha?.close).toBe((10 + 14 + 8 + 12) / 4);
    // The first open seeds from the raw open and close.
    expect(ha?.open).toBe(11);
  });

  it('opens each bar at the midpoint of the previous HA bar', () => {
    const bars = makeBars([10, 12, 14]);
    const ha = heikinAshi(bars);
    const first = ha[0] as Bar;
    expect(ha[1]?.open).toBe((first.open + first.close) / 2);
  });

  it('keeps high and low enclosing the body', () => {
    const bars = makeBars(Array.from({ length: 30 }, (_, i) => 100 + Math.sin(i) * 5));
    for (const bar of heikinAshi(bars)) {
      expect(bar.high).toBeGreaterThanOrEqual(Math.max(bar.open, bar.close));
      expect(bar.low).toBeLessThanOrEqual(Math.min(bar.open, bar.close));
    }
  });

  it('preserves timestamps', () => {
    const bars = makeBars([1, 2, 3]);
    expect(heikinAshi(bars).map((b) => b.time)).toEqual(bars.map((b) => b.time));
  });
});

describe('alignment', () => {
  it('every indicator returns a series the same length as its input', () => {
    const values = Array.from({ length: 80 }, (_, i) => 100 + i);
    const bars = makeBars(values);

    expect(sma(values, 20)).toHaveLength(80);
    expect(ema(values, 20)).toHaveLength(80);
    expect(rsi(values, 14)).toHaveLength(80);
    expect(macd(values).macd).toHaveLength(80);
    expect(atr(bars, 14)).toHaveLength(80);
    expect(bollinger(values, 20).middle).toHaveLength(80);
  });
});
