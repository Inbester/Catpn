/**
 * Indicator maths.
 *
 * Pure functions over closed bars. Phase 2's strategy engine runs the same
 * definitions server-side, so these follow the standard formulas exactly —
 * a chart that disagrees with the backtest is worse than no chart.
 *
 * Every series is returned aligned to the input: index `i` is the value at
 * bar `i`, with `null` where there is not yet enough history. Returning
 * `null` rather than a partial value keeps a half-warmed average from
 * looking like a signal.
 */

import type { Bar } from './types';

export type Series = Array<number | null>;

export interface IndicatorDefinition {
  id: string;
  name: string;
  /** Overlay indicators draw on the price pane; others get their own. */
  overlay: boolean;
}

/** Simple moving average. */
export function sma(values: number[], length: number): Series {
  if (length < 1) throw new RangeError('SMA length must be at least 1');
  const out: Series = new Array<number | null>(values.length).fill(null);
  let sum = 0;

  for (let i = 0; i < values.length; i += 1) {
    sum += values[i] as number;
    if (i >= length) sum -= values[i - length] as number;
    if (i >= length - 1) out[i] = sum / length;
  }
  return out;
}

/**
 * Exponential moving average.
 *
 * Seeded with the SMA of the first `length` values, which is the
 * conventional warm-up and keeps the result independent of how much
 * history happens to be loaded.
 */
export function ema(values: number[], length: number): Series {
  if (length < 1) throw new RangeError('EMA length must be at least 1');
  const out: Series = new Array<number | null>(values.length).fill(null);
  if (values.length < length) return out;

  const k = 2 / (length + 1);
  let seed = 0;
  for (let i = 0; i < length; i += 1) seed += values[i] as number;

  let previous = seed / length;
  out[length - 1] = previous;

  for (let i = length; i < values.length; i += 1) {
    previous = (values[i] as number) * k + previous * (1 - k);
    out[i] = previous;
  }
  return out;
}

/** Wilder's smoothing, used by RSI and ATR (not the same as an EMA). */
function wilder(values: number[], length: number): Series {
  const out: Series = new Array<number | null>(values.length).fill(null);
  if (values.length < length) return out;

  let sum = 0;
  for (let i = 0; i < length; i += 1) sum += values[i] as number;

  let previous = sum / length;
  out[length - 1] = previous;

  for (let i = length; i < values.length; i += 1) {
    previous = (previous * (length - 1) + (values[i] as number)) / length;
    out[i] = previous;
  }
  return out;
}

/** Relative strength index, Wilder's original formulation. */
export function rsi(values: number[], length = 14): Series {
  const out: Series = new Array<number | null>(values.length).fill(null);
  if (values.length <= length) return out;

  const gains: number[] = [];
  const losses: number[] = [];
  for (let i = 1; i < values.length; i += 1) {
    const change = (values[i] as number) - (values[i - 1] as number);
    gains.push(Math.max(change, 0));
    losses.push(Math.max(-change, 0));
  }

  const avgGain = wilder(gains, length);
  const avgLoss = wilder(losses, length);

  for (let i = 0; i < gains.length; i += 1) {
    const gain = avgGain[i];
    const loss = avgLoss[i];
    if (gain === null || gain === undefined || loss === null || loss === undefined) continue;
    // All-gain windows are RSI 100 by definition; guard the division.
    out[i + 1] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  }
  return out;
}

export interface MacdResult {
  macd: Series;
  signal: Series;
  histogram: Series;
}

/** MACD: fast EMA − slow EMA, with an EMA signal line. */
export function macd(values: number[], fast = 12, slow = 26, signalLength = 9): MacdResult {
  const fastEma = ema(values, fast);
  const slowEma = ema(values, slow);

  const macdLine: Series = values.map((_, i) => {
    const f = fastEma[i];
    const s = slowEma[i];
    return f === null || f === undefined || s === null || s === undefined ? null : f - s;
  });

  // The signal line is an EMA of the MACD line, which only starts once the
  // slow EMA has warmed up.
  const firstValue = macdLine.findIndex((v) => v !== null);
  const signal: Series = new Array<number | null>(values.length).fill(null);
  const histogram: Series = new Array<number | null>(values.length).fill(null);

  if (firstValue !== -1) {
    const dense = macdLine.slice(firstValue) as number[];
    const signalDense = ema(dense, signalLength);
    for (let i = 0; i < signalDense.length; i += 1) {
      const value = signalDense[i];
      if (value === null || value === undefined) continue;
      const index = firstValue + i;
      signal[index] = value;
      const m = macdLine[index];
      if (m !== null && m !== undefined) histogram[index] = m - value;
    }
  }

  return { macd: macdLine, signal, histogram };
}

/** True range for each bar; the first has no previous close. */
function trueRange(bars: Bar[]): number[] {
  return bars.map((bar, i) => {
    if (i === 0) return bar.high - bar.low;
    const previousClose = (bars[i - 1] as Bar).close;
    return Math.max(
      bar.high - bar.low,
      Math.abs(bar.high - previousClose),
      Math.abs(bar.low - previousClose),
    );
  });
}

/** Average true range, Wilder-smoothed. Drives the ATR stop in phase 2. */
export function atr(bars: Bar[], length = 14): Series {
  return wilder(trueRange(bars), length);
}

export interface BollingerResult {
  middle: Series;
  upper: Series;
  lower: Series;
}

/** Bollinger Bands: an SMA with population standard deviation bands. */
export function bollinger(values: number[], length = 20, multiplier = 2): BollingerResult {
  const middle = sma(values, length);
  const upper: Series = new Array<number | null>(values.length).fill(null);
  const lower: Series = new Array<number | null>(values.length).fill(null);

  for (let i = length - 1; i < values.length; i += 1) {
    const mean = middle[i];
    if (mean === null || mean === undefined) continue;

    let variance = 0;
    for (let k = i - length + 1; k <= i; k += 1) {
      const diff = (values[k] as number) - mean;
      variance += diff * diff;
    }
    const deviation = Math.sqrt(variance / length);
    upper[i] = mean + deviation * multiplier;
    lower[i] = mean - deviation * multiplier;
  }

  return { middle, upper, lower };
}

/**
 * Heikin-Ashi candles.
 *
 * A chart type rather than an indicator, but the same kind of derived
 * series. The first bar seeds from the raw open and close.
 */
export function heikinAshi(bars: Bar[]): Bar[] {
  const out: Bar[] = [];

  for (let i = 0; i < bars.length; i += 1) {
    const bar = bars[i] as Bar;
    const close = (bar.open + bar.high + bar.low + bar.close) / 4;
    const previous = out[i - 1];
    const open = previous ? (previous.open + previous.close) / 2 : (bar.open + bar.close) / 2;

    out.push({
      time: bar.time,
      open,
      close,
      high: Math.max(bar.high, open, close),
      low: Math.min(bar.low, open, close),
      volume: bar.volume,
      closed: bar.closed,
    });
  }
  return out;
}

export const closes = (bars: Bar[]): number[] => bars.map((b) => b.close);
