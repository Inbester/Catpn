/** Strategy and backtest shapes, mirroring quanta/schemas/strategy.py. */

export interface ExitRules {
  atr_stop_multiple: number | null;
  atr_length: number;
  take_profit_r: number | null;
  break_even_at_r: number | null;
  trailing_atr_multiple: number | null;
  exit_on_opposite: boolean;
  time_exit_bars: number | null;
}

export const DEFAULT_EXITS: ExitRules = {
  atr_stop_multiple: null,
  atr_length: 14,
  take_profit_r: null,
  break_even_at_r: null,
  trailing_atr_multiple: null,
  exit_on_opposite: true,
  time_exit_bars: null,
};

export interface StrategyPayload {
  name: string;
  description?: string | null;
  long_entry: string | null;
  short_entry: string | null;
  exits: ExitRules;
  params: Record<string, number>;
}

export interface Strategy extends StrategyPayload {
  id: string;
  version: string;
  created_at: string;
  updated_at: string;
}

export interface ValidationResult {
  valid: boolean;
  version: string | null;
  error: string | null;
  position: number | null;
  normalized_long: string | null;
  normalized_short: string | null;
}

export interface FunctionReference {
  name: string;
  min_args: number;
  max_args: number;
  doc: string;
}

export interface BacktestConfig {
  initial_capital: number;
  margin_percent: number;
  leverage: number;
  margin_mode: 'isolated' | 'cross';
  maker_fee: number;
  taker_fee: number;
  slippage_bps: number;
  apply_funding: boolean;
  use_magnifier: boolean;
}

export const DEFAULT_CONFIG: BacktestConfig = {
  initial_capital: 10_000,
  margin_percent: 10,
  leverage: 10,
  margin_mode: 'isolated',
  // Bitunix VIP0 (SPEC §6). Never zero by default: a backtest that forgets
  // costs reports a strategy that does not exist.
  maker_fee: 0.0002,
  taker_fee: 0.0006,
  slippage_bps: 1,
  apply_funding: true,
  use_magnifier: true,
};

export interface Trade {
  side: 'long' | 'short';
  entry_time: number;
  entry_price: number;
  exit_time: number;
  exit_price: number;
  quantity: number;
  margin: number;
  leverage: number;
  liquidation_price: number;
  exit_reason: string;
  gross_pnl: number;
  fees: number;
  funding: number;
  net_pnl: number;
  return_on_margin: number;
  run_up: number;
  drawdown: number;
  bars_held: number;
  equity_after: number;
}

export interface BacktestStats {
  net_profit: number;
  net_profit_percent: number;
  ending_equity: number;
  buy_and_hold_percent: number;
  max_drawdown_percent: number;
  longest_drawdown_bars: number;
  sharpe: number | null;
  sortino: number | null;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate_percent: number;
  profit_factor: number | null;
  average_win: number | null;
  average_loss: number | null;
  largest_win: number;
  largest_loss: number;
  average_bars_held: number | null;
  gross_profit: number;
  total_fees: number;
  total_funding: number;
  costs_over_gross: number | null;
  long_trades: number;
  short_trades: number;
  long_net_pnl: number;
  short_net_pnl: number;
  liquidations: number;
}

export interface BacktestRun {
  id: string;
  strategy_id: string;
  strategy_version: string;
  symbol: string;
  interval: string;
  start_time: number;
  end_time: number;
  config: Record<string, unknown>;
  stats: BacktestStats;
  trades: Trade[];
  equity: { time: number[]; value: number[]; drawdown: number[] };
  duration_ms: number;
  created_at: string;
}

export interface BacktestSummary {
  id: string;
  strategy_id: string;
  strategy_version: string;
  symbol: string;
  interval: string;
  stats: BacktestStats;
  duration_ms: number;
  created_at: string;
}

/** A readable label for an exit reason. */
export const EXIT_REASON_LABELS: Record<string, string> = {
  take_profit: 'Take profit',
  stop_loss: 'Stop loss',
  trailing_stop: 'Trailing stop',
  break_even: 'Break even',
  opposite_signal: 'Opposite signal',
  time_exit: 'Time exit',
  liquidation: 'Liquidation',
  end_of_data: 'End of data',
};
