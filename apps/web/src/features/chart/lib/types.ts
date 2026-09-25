/** Chart domain types, mirroring the market-data API. */

export const INTERVALS = [
  '1m',
  '5m',
  '15m',
  '30m',
  '1h',
  '2h',
  '4h',
  '6h',
  '8h',
  '12h',
  '1d',
  '3d',
  '1w',
  '1M',
] as const;

export type Interval = (typeof INTERVALS)[number];

/** Timeframes shown as buttons; the rest live behind the dropdown. */
export const QUICK_INTERVALS: readonly Interval[] = ['1m', '5m', '15m', '1h', '4h', '1d'];

export const INTERVAL_SECONDS: Record<Interval, number> = {
  '1m': 60,
  '5m': 300,
  '15m': 900,
  '30m': 1800,
  '1h': 3600,
  '2h': 7200,
  '4h': 14_400,
  '6h': 21_600,
  '8h': 28_800,
  '12h': 43_200,
  '1d': 86_400,
  '3d': 259_200,
  '1w': 604_800,
  // Only used for coarse sizing, never for bar boundaries.
  '1M': 2_592_000,
};

export function isInterval(value: string): value is Interval {
  return (INTERVALS as readonly string[]).includes(value);
}

export type PriceType = 'LAST' | 'MARK';

export const CHART_TYPES = ['candles', 'hollow', 'heikin-ashi', 'bars', 'line', 'area'] as const;
export type ChartType = (typeof CHART_TYPES)[number];

/**
 * One bar.
 *
 * Numbers, not strings: the chart library needs them as numbers, and the
 * conversion happens once here at the boundary rather than in every consumer.
 * The wire format keeps full precision as strings (see the API's rationale);
 * for drawing, a double is more than enough.
 */
export interface Bar {
  /** Bar open time, epoch milliseconds, on a UTC boundary. */
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  closed: boolean;
}

/** The wire shape from /market/klines and the stream. */
export interface WireBar {
  t: number;
  o: string;
  h: string;
  l: string;
  c: string;
  v: string;
  closed: boolean;
}

export function toBar(wire: WireBar): Bar {
  return {
    time: wire.t,
    open: Number(wire.o),
    high: Number(wire.h),
    low: Number(wire.l),
    close: Number(wire.c),
    volume: Number(wire.v),
    closed: wire.closed,
  };
}

export interface KlineResponse {
  symbol: string;
  interval: string;
  price_type: string;
  bars: WireBar[];
}

export interface Instrument {
  symbol: string;
  base: string;
  quote: string;
  min_leverage: number;
  max_leverage: number;
  default_leverage: number;
  base_precision: number;
  quote_precision: number;
  status: string;
}

export interface Ticker {
  symbol: string;
  last: string;
  change_percent_24h: string;
  high_24h: string | null;
  low_24h: string | null;
  quote_volume_24h: string | null;
  mark_price: string | null;
  index_price: string | null;
  funding_rate: string | null;
  next_funding_time: number | null;
  open_interest: string | null;
}

/** A frame from the /market/stream WebSocket. */
export interface StreamMessage {
  type: 'kline' | 'ticker' | 'mark_price';
  symbol: string;
  ts: number;
  interval?: string;
  bar?: WireBar;
  ticker?: {
    symbol: string;
    last: string;
    change24h: string;
    mark: string | null;
    index: string | null;
    fundingRate: string | null;
    nextFundingTime: number | null;
    high24h: string | null;
    low24h: string | null;
    openInterest: string | null;
  };
  price?: string;
}
