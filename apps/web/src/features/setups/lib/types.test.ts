import { describe, expect, it } from 'vitest';

import { stageStatus, usedIn, type Setup, type StageState } from './types';

function setup(overrides: Partial<Setup> = {}): Setup {
  return {
    id: 'a',
    name: 'BTC 1h Trend',
    color: '#6EA8FE',
    strategy_id: 's',
    strategy_version: 'abc123def456',
    strategy_snapshot: {},
    symbol: 'BTCUSDT',
    interval: '1h',
    margin_percent: 10,
    leverage: 5,
    margin_mode: 'isolated',
    exposure: 50,
    fee_tier: 'VIP0',
    maker_fee: 0.0002,
    taker_fee: 0.0006,
    max_drawdown_budget_percent: null,
    risk_of_ruin_limit_percent: null,
    source_run_id: null,
    pipeline: {},
    use_in_backtest: true,
    use_in_forward: true,
    use_in_paper: false,
    use_in_alerts: false,
    use_in_bot: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('stageStatus', () => {
  it('reads a recorded stage', () => {
    const passed: StageState = { status: 'passed' };
    expect(stageStatus(setup({ pipeline: { backtest: passed } }), 'backtest')).toBe('passed');
  });

  it('treats a stage the pipeline never mentions as not started', () => {
    // The server only writes stages that have been touched, so an absent
    // key is the normal case for a new setup — not a missing-data bug.
    expect(stageStatus(setup(), 'bot')).toBe('not_started');
  });
});

describe('usedIn', () => {
  it('lists the enabled uses in pipeline order', () => {
    expect(usedIn(setup({ use_in_alerts: true }))).toEqual(['backtest', 'forward', 'alerts']);
  });

  it('returns nothing when a setup is switched off everywhere', () => {
    expect(usedIn(setup({ use_in_backtest: false, use_in_forward: false }))).toEqual([]);
  });
});
