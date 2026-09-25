/**
 * Bridge the CSS design tokens into Lightweight Charts options.
 *
 * The chart draws to a canvas, so it cannot inherit CSS variables. Reading
 * them at build time keeps one source of truth: change a token and both the
 * chrome and the chart follow.
 */

import type { ChartOptions, DeepPartial } from 'lightweight-charts';
import { ColorType, CrosshairMode, LineStyle } from 'lightweight-charts';

export function token(name: string, fallback = '#000'): string {
  if (typeof window === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export interface ChartPalette {
  bg: string;
  text: string;
  muted: string;
  dim: string;
  line: string;
  line2: string;
  up: string;
  down: string;
  amber: string;
  drawing: string;
  series1: string;
  series2: string;
  series3: string;
  fontMono: string;
}

export function readPalette(): ChartPalette {
  return {
    bg: token('--bg', '#0B0C0E'),
    text: token('--text', '#E7E9EC'),
    muted: token('--muted', '#7D848E'),
    dim: token('--dim', '#4A5059'),
    line: token('--line', '#1C1F23'),
    line2: token('--line-2', '#15171A'),
    up: token('--up', '#2EBD85'),
    down: token('--down', '#F0506E'),
    amber: token('--amber', '#F59E0B'),
    drawing: token('--drawing', '#6EA8FE'),
    series1: token('--series-1', '#C9CDD3'),
    series2: token('--series-2', '#6B727C'),
    series3: token('--series-3', '#D9B26A'),
    fontMono: token('--font-mono', 'monospace'),
  };
}

export function chartOptions(palette: ChartPalette): DeepPartial<ChartOptions> {
  return {
    layout: {
      background: { type: ColorType.Solid, color: palette.bg },
      textColor: palette.muted,
      fontSize: 11,
      fontFamily: palette.fontMono,
      attributionLogo: false,
      panes: { separatorColor: palette.line, separatorHoverColor: palette.dim },
    },
    grid: {
      vertLines: { color: palette.line2 },
      horzLines: { color: palette.line2 },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: {
        color: palette.dim,
        width: 1,
        style: LineStyle.Dashed,
        labelBackgroundColor: palette.line,
      },
      horzLine: {
        color: palette.dim,
        width: 1,
        style: LineStyle.Dashed,
        labelBackgroundColor: palette.line,
      },
    },
    rightPriceScale: {
      borderColor: palette.line,
      scaleMargins: { top: 0.08, bottom: 0.08 },
    },
    timeScale: {
      borderColor: palette.line,
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 6,
      barSpacing: 8,
    },
    localization: {
      // Bar boundaries are UTC everywhere in the product (SPEC §3.1); the
      // displayed clock is handled by the bottom bar's timezone control.
      locale: 'en-US',
    },
    autoSize: true,
  };
}

export function candleOptions(palette: ChartPalette, hollow: boolean) {
  return {
    upColor: hollow ? 'transparent' : palette.up,
    downColor: hollow ? 'transparent' : palette.down,
    borderUpColor: palette.up,
    borderDownColor: palette.down,
    wickUpColor: palette.up,
    wickDownColor: palette.down,
    borderVisible: true,
  };
}
