/** Forward-test shapes, mirroring quanta_engine.forward. */

export type VerdictKey = 'holds_up' | 'holds_up_weaker' | 'outside_range' | 'too_few_trades';

export const VERDICT_LABELS: Record<VerdictKey, string> = {
  holds_up: 'HOLDS UP',
  holds_up_weaker: 'HOLDS UP · WEAKER',
  outside_range: 'OUTSIDE RANGE',
  too_few_trades: 'TOO FEW TRADES',
};

export interface Check {
  key: string;
  label: string;
  passed: boolean;
  severity: 'ok' | 'warn' | 'fail';
  detail: string;
}

export interface MetricBand {
  low: number;
  high: number;
  median: number;
  position: number;
  contains: boolean;
}

export interface MetricRow {
  key: string;
  label: string;
  reference: number;
  test: number;
  change: number;
  unit: string;
  higher_is_better: boolean;
  band: MetricBand | null;
}

export interface Regime {
  return_percent: number;
  volatility_annual_percent: number;
  trend_efficiency: number;
  average_candle_range_percent: number;
  bars: number;
}

export interface PeriodSummary {
  label: string;
  start: number;
  end: number;
  stats: Record<string, number | null>;
  regime: Regime;
  equity_by_trade: number[];
}

export interface ComparisonResult {
  verdict: VerdictKey;
  headline: string;
  explanation: string;
  reading: string;
  checks: Check[];
  metrics: MetricRow[];
  reference: PeriodSummary;
  test: PeriodSummary;
  strategy_version: string;
  monte_carlo: {
    runs: number;
    confidence: number;
    net: { low: number; high: number; median: number };
    drawdown: { low: number; high: number; median: number };
    worst_case_equity: number[];
    best_case_equity: number[];
    median_equity: number[];
  };
}

export interface WalkForwardWindow {
  index: number;
  in_sample_start: number;
  in_sample_end: number;
  out_of_sample_start: number;
  out_of_sample_end: number;
  chosen_params: Record<string, number>;
  in_sample_net_percent: number;
  out_of_sample_net_percent: number;
  out_of_sample_max_drawdown: number;
  out_of_sample_trades: number;
  efficiency: number | null;
  selected: boolean;
  note: string;
}

export interface WalkForwardResult {
  windows: WalkForwardWindow[];
  chained: { time: number[]; value: number[]; drawdown: number[] };
  walk_forward_efficiency: number | null;
  total_net_percent: number;
  max_drawdown_percent: number;
  total_trades: number;
}
