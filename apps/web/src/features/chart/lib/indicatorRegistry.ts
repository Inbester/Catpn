/**
 * The indicators a user can add, and how each one draws.
 *
 * Keeping the definitions in one table means the Indicators dialog, the
 * legend and the rendering all agree, and adding one is a single entry.
 */

import { atr, bollinger, closes, ema, macd, rsi, sma, type Series } from './indicators';
import type { Bar } from './types';

export type IndicatorId = 'ema' | 'sma' | 'bb' | 'volume' | 'rsi' | 'macd' | 'atr';

export interface IndicatorParams {
  length?: number;
  fast?: number;
  slow?: number;
  signal?: number;
  multiplier?: number;
}

/** One configured indicator on the chart. */
export interface IndicatorInstance {
  /** Stable id, so state survives reordering and reloads. */
  key: string;
  id: IndicatorId;
  params: IndicatorParams;
  visible: boolean;
  color?: string;
}

export interface PlotLine {
  label: string;
  values: Series;
  color: string;
  lineWidth?: 1 | 2;
  /** Drawn as a histogram rather than a line (MACD). */
  histogram?: boolean;
}

export interface IndicatorDefinition {
  id: IndicatorId;
  name: string;
  /** Overlays draw on the price pane; the rest get their own pane. */
  overlay: boolean;
  defaults: IndicatorParams;
  /** Fixed reference levels drawn in the pane, e.g. RSI 30/70. */
  levels?: number[];
  /** A fixed 0-100 scale, so the pane does not rescale to noise. */
  fixedRange?: [number, number];
  compute: (bars: Bar[], params: IndicatorParams, palette: Palette) => PlotLine[];
  label: (params: IndicatorParams) => string;
}

export interface Palette {
  series1: string;
  series2: string;
  series3: string;
  up: string;
  down: string;
  amber: string;
}

export const INDICATORS: Record<IndicatorId, IndicatorDefinition> = {
  ema: {
    id: 'ema',
    name: 'EMA',
    overlay: true,
    defaults: { length: 20 },
    label: (p) => `EMA ${p.length ?? 20}`,
    compute: (bars, p, palette) => [
      {
        label: `EMA ${p.length ?? 20}`,
        values: ema(closes(bars), p.length ?? 20),
        color: palette.series1,
      },
    ],
  },
  sma: {
    id: 'sma',
    name: 'SMA',
    overlay: true,
    defaults: { length: 50 },
    label: (p) => `SMA ${p.length ?? 50}`,
    compute: (bars, p, palette) => [
      {
        label: `SMA ${p.length ?? 50}`,
        values: sma(closes(bars), p.length ?? 50),
        color: palette.series2,
      },
    ],
  },
  bb: {
    id: 'bb',
    name: 'Bollinger Bands',
    overlay: true,
    defaults: { length: 20, multiplier: 2 },
    label: (p) => `BB ${p.length ?? 20} ${p.multiplier ?? 2}`,
    compute: (bars, p, palette) => {
      const result = bollinger(closes(bars), p.length ?? 20, p.multiplier ?? 2);
      return [
        { label: 'Upper', values: result.upper, color: palette.series2 },
        { label: 'Basis', values: result.middle, color: palette.series1 },
        { label: 'Lower', values: result.lower, color: palette.series2 },
      ];
    },
  },
  volume: {
    id: 'volume',
    name: 'Volume',
    overlay: false,
    defaults: {},
    label: () => 'Volume',
    compute: (bars, _p, palette) => [
      {
        label: 'Vol',
        values: bars.map((b) => b.volume),
        color: palette.series2,
        histogram: true,
      },
    ],
  },
  rsi: {
    id: 'rsi',
    name: 'RSI',
    overlay: false,
    defaults: { length: 14 },
    levels: [30, 50, 70],
    fixedRange: [0, 100],
    label: (p) => `RSI ${p.length ?? 14}`,
    compute: (bars, p, palette) => [
      {
        label: `RSI ${p.length ?? 14}`,
        values: rsi(closes(bars), p.length ?? 14),
        color: palette.series1,
      },
    ],
  },
  macd: {
    id: 'macd',
    name: 'MACD',
    overlay: false,
    defaults: { fast: 12, slow: 26, signal: 9 },
    levels: [0],
    label: (p) => `MACD ${p.fast ?? 12} ${p.slow ?? 26} ${p.signal ?? 9}`,
    compute: (bars, p, palette) => {
      const result = macd(closes(bars), p.fast ?? 12, p.slow ?? 26, p.signal ?? 9);
      return [
        { label: 'Hist', values: result.histogram, color: palette.series2, histogram: true },
        { label: 'MACD', values: result.macd, color: palette.series1 },
        { label: 'Signal', values: result.signal, color: palette.series3 },
      ];
    },
  },
  atr: {
    id: 'atr',
    name: 'ATR',
    overlay: false,
    defaults: { length: 14 },
    label: (p) => `ATR ${p.length ?? 14}`,
    compute: (bars, p, palette) => [
      {
        label: `ATR ${p.length ?? 14}`,
        values: atr(bars, p.length ?? 14),
        color: palette.amber,
      },
    ],
  },
};

export const INDICATOR_LIST: IndicatorDefinition[] = Object.values(INDICATORS);

let counter = 0;

export function createIndicator(id: IndicatorId, params?: IndicatorParams): IndicatorInstance {
  counter += 1;
  return {
    key: `${id}-${Date.now().toString(36)}-${counter}`,
    id,
    params: { ...INDICATORS[id].defaults, ...params },
    visible: true,
  };
}

/** The indicators a fresh chart starts with, matching the approved mockup. */
export function defaultIndicators(): IndicatorInstance[] {
  return [
    createIndicator('volume'),
    createIndicator('ema', { length: 20 }),
    createIndicator('ema', { length: 50 }),
  ];
}
