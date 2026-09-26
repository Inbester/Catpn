/** Alert shapes, mirroring quanta.schemas.alert. */

export type AlertSource = 'strategy' | 'price' | 'indicator' | 'risk' | 'market' | 'system';
export type RepeatMode = 'every' | 'once' | 'once_per_bar';
export type TriggerMode = 'bar_close' | 'tick';
export type DestinationKind = 'telegram' | 'web_push' | 'webhook' | 'email';

/**
 * The orders these appear in. The labels themselves live in the
 * translation bundle, so the wording is in one place rather than split
 * between a bundle and a constant here.
 */
export const ALERT_SOURCES: readonly AlertSource[] = [
  'strategy',
  'price',
  'indicator',
  'risk',
  'market',
  'system',
];

export const REPEAT_MODES: readonly RepeatMode[] = ['every', 'once', 'once_per_bar'];

export interface Destination {
  kind: DestinationKind;
  target: string;
  label?: string;
  secret?: string;
}

export interface Alert {
  id: string;
  name: string;
  source: AlertSource;
  setup_id: string | null;
  symbol: string;
  interval: string;
  condition: Record<string, unknown>;
  trigger_mode: TriggerMode;
  repeat_mode: RepeatMode;
  expires_at: string | null;
  quiet_from_hour: number | null;
  quiet_to_hour: number | null;
  template: string;
  locale: 'en' | 'fa';
  destinations: Destination[];
  enabled: boolean;
  last_fired_at: string | null;
  fire_count: number;
  created_at: string;
}

export interface Delivery {
  kind: string;
  target?: string;
  state: 'pending' | 'sent' | 'failed' | 'suppressed';
  latency_ms?: number;
  attempts?: number;
  note?: string;
}

export interface AlertEvent {
  id: string;
  alert_id: string;
  bar_time: number;
  price: string;
  message: string;
  /** Above one means a burst was folded into this single message. */
  merged_count: number;
  quiet: boolean;
  deliveries: Delivery[];
  created_at: string;
}

export interface Channel {
  id: string;
  kind: DestinationKind;
  label: string;
  target: string;
  verified: boolean;
  enabled: boolean;
  created_at: string;
}

export interface PromotionCheck {
  key: string;
  label: string;
  passed: boolean;
  detail: string;
}

export interface PaperSession {
  id: string;
  setup_id: string;
  state: 'running' | 'paused' | 'stopped' | 'promoted';
  started_at: string;
  initial_capital: number;
  equity: number;
  net_percent: number;
  max_drawdown_percent: number;
  missed_signals: number;
  expected: {
    net_percent: number | null;
    low_percent: number | null;
    high_percent: number | null;
    drawdown_limit_percent: number | null;
  };
  execution: {
    fills: number;
    mean_latency_ms: number;
    mean_slippage_bps: number;
    drift_percent: number;
    total_fees: number;
    total_funding: number;
  };
  equity_curve: { time: number; equity: number }[];
  promotion: { ready: boolean; blocking: string[]; checks: PromotionCheck[] };
  promoted_at: string | null;
  promoted_by_override: boolean;
}
