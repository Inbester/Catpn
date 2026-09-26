/** Research study shapes, mirroring quanta.schemas.research. */

export interface Cell {
  margin_percent: number;
  leverage: number;
  net_percent: number;
  annualised_percent: number;
  max_drawdown_percent: number;
  liquidations: number;
  trades: number;
  costs_over_gross: number | null;
  worst_trade_percent: number;
  /** Margin share times leverage: what the position actually controls. */
  exposure: number;
}

export interface MarginModeRow {
  margin_mode: 'isolated' | 'cross';
  exposure: number;
  liquidation_distance_percent: number;
  net_percent: number;
  max_drawdown_percent: number;
  worst_trade_percent: number;
  liquidations: number;
  costs_over_gross: number | null;
  risk_of_ruin_percent: number;
}

export interface LeverageStudy {
  symbol: string;
  interval: string;
  strategy_version: string;
  bars: number;
  budget_percent: number | null;
  cells: Cell[];
  recommendation: {
    cell: Cell | null;
    reason: string;
    best_net_cell: Cell | null;
  };
  margin_modes: MarginModeRow[];
}

export interface TradePoint {
  index: number;
  side: 'long' | 'short';
  entry_time: number;
  bars_held: number;
  adverse_percent: number;
  favourable_percent: number;
  result_percent: number;
  funding_paid: number;
  was_liquidated: boolean;
  recovered: boolean;
}

export interface TradeRiskStudy {
  symbol: string;
  interval: string;
  strategy_version: string;
  points: TradePoint[];
  kpis: {
    winners: number;
    winners_that_were_red: number;
    median_dip_percent: number;
    p95_dip_percent: number;
    deepest_dip_percent: number;
    survives_up_to_leverage: number;
    worst_closed_trade_percent: number;
    average_bars_held: number;
    funding_events: number;
    total_funding: number;
  };
  holding: {
    from_bars: number;
    to_bars: number;
    trades: number;
    net_funding: number;
    mean_result_percent: number;
  }[];
}

export interface StressCase {
  name: string;
  description: string;
  net_percent: number;
  max_drawdown_percent: number;
  trades: number;
  delta_percent: number;
  survived: boolean;
  /** False for VIP3 fees: cheaper than the default, so it is a what-if. */
  adverse: boolean;
}

export interface ParameterPoint {
  params: Record<string, number>;
  net_percent: number;
  max_drawdown_percent: number;
  trades: number;
}

export interface RobustnessStudy {
  symbol: string;
  interval: string;
  strategy_version: string;
  stress: StressCase[];
  reshuffled: {
    median_percent: number;
    p5_percent: number;
    p95_percent: number;
    ruin_rate: number;
  };
  trades_per_year: number;
  risk: {
    var_95_percent: number;
    cvar_95_percent: number;
    kelly_fraction: number;
    half_kelly_fraction: number;
  };
  surface: {
    points: ParameterPoint[];
    best: ParameterPoint | null;
    neighbourhood_mean_percent: number;
    plateau: boolean;
  };
}

export interface DiscoverPlan {
  series: { key: string; label: string; scale: string; source: string }[];
  primitives: number;
  filters: number;
  triggers: number;
  raw_combinations: number;
  rules: number;
  tests: number;
}

export interface DiscoverHit {
  rule_key: string;
  side: 'long' | 'short';
  horizon: number;
  signals: number;
  mean_return_percent: number;
  mean_net_percent: number;
  t_statistic: number;
  p_value: number;
  win_rate: number;
  out_of_sample_mean_percent: number;
  out_of_sample_signals: number;
}

export interface DiscoverResult {
  tested: number;
  /** What an uncorrected search would have called significant. */
  significant_uncorrected: number;
  expected_false_hits: number;
  threshold_p: number;
  in_sample_bars: number;
  out_of_sample_bars: number;
  hits: DiscoverHit[];
  hits_total: number;
}

export interface ServerJob {
  id: string;
  kind: string;
  label: string;
  state: 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
  done: number;
  total: number;
  percent: number;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  result?: DiscoverResult | null;
}

export interface SourceInfo {
  key: string;
  label: string;
  lines: string[];
}
