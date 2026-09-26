/** Setup shapes, mirroring quanta.schemas.forward. */

export const PIPELINE_STAGES = [
  'research',
  'backtest',
  'forward',
  'paper',
  'alerts',
  'bot',
] as const;

export type Stage = (typeof PIPELINE_STAGES)[number];

export type StageStatus = 'not_started' | 'running' | 'passed' | 'failed';

/** Short labels for the stage chips, in the order the pipeline runs. */
export const STAGE_LABELS: Record<Stage, string> = {
  research: 'RES',
  backtest: 'BT',
  forward: 'FWD',
  paper: 'PAPER',
  alerts: 'ALERT',
  bot: 'BOT',
};

export const STAGE_NAMES: Record<Stage, string> = {
  research: 'Research',
  backtest: 'Backtest',
  forward: 'Forward',
  paper: 'Paper',
  alerts: 'Alerts',
  bot: 'Bot',
};

export interface StageState {
  status: StageStatus;
  updated_at?: string;
  note?: string;
}

/** The palette the API accepts. Colour identifies a Setup; it never ranks one. */
export const SETUP_COLORS = [
  '#6EA8FE',
  '#2EBD85',
  '#F59E0B',
  '#F0506E',
  '#A78BFA',
  '#38BDF8',
  '#FB923C',
  '#94A3B8',
] as const;

export interface Setup {
  id: string;
  name: string;
  color: string;
  strategy_id: string;
  strategy_version: string;
  strategy_snapshot: Record<string, unknown>;
  symbol: string;
  interval: string;
  margin_percent: number;
  leverage: number;
  margin_mode: 'isolated' | 'cross';
  exposure: number;
  fee_tier: string;
  maker_fee: number;
  taker_fee: number;
  max_drawdown_budget_percent: number | null;
  risk_of_ruin_limit_percent: number | null;
  source_run_id: string | null;
  pipeline: Partial<Record<Stage, StageState>>;
  use_in_backtest: boolean;
  use_in_forward: boolean;
  use_in_paper: boolean;
  use_in_alerts: boolean;
  use_in_bot: boolean;
  created_at: string;
  updated_at: string;
}

/** The kinds the server emits today; it may add more, so this is not a union. */
export type ConflictKind = string;

export interface ConflictWarning {
  kind: ConflictKind;
  message: string;
  setup_ids: string[];
}

export interface SetupsOverview {
  setups: Setup[];
  total_exposure: number;
  conflicts: ConflictWarning[];
}

export function stageStatus(setup: Setup, stage: Stage): StageStatus {
  return setup.pipeline[stage]?.status ?? 'not_started';
}

/**
 * Where a Setup is switched on, in pipeline order.
 *
 * Returns stage keys rather than labels: the caller translates them, and a
 * function that returned English would be one more place to find when the
 * Persian pass came round.
 */
export function usedIn(setup: Setup): string[] {
  const uses: [boolean, string][] = [
    [setup.use_in_backtest, 'backtest'],
    [setup.use_in_forward, 'forward'],
    [setup.use_in_paper, 'paper'],
    [setup.use_in_alerts, 'alerts'],
    [setup.use_in_bot, 'bot'],
  ];
  return uses.filter(([on]) => on).map(([, key]) => key);
}
