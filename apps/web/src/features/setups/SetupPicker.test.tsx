import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./lib/api', () => ({
  listSetups: vi.fn(() => Promise.resolve(mockSetups)),
}));

import { SetupPicker } from './SetupPicker';
import { useSetupsStore } from './lib/store';
import type { Setup } from './lib/types';

function setup(overrides: Partial<Setup> = {}): Setup {
  return {
    id: 'a',
    name: 'BTC 1h Trend',
    color: '#6EA8FE',
    strategy_id: 's',
    strategy_version: 'abc123def456789',
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
    pipeline: { backtest: { status: 'passed' } },
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

const SETUPS = [
  setup(),
  setup({ id: 'b', name: 'ETH 4h Swing', symbol: 'ETHUSDT', interval: '4h' }),
];

// Read by the mocked listSetups above, which is hoisted past this line.
let mockSetups: Setup[] = SETUPS;

function renderPicker() {
  return render(
    <MemoryRouter>
      <SetupPicker />
    </MemoryRouter>,
  );
}

describe('SetupPicker', () => {
  beforeEach(() => {
    useSetupsStore.setState({ setups: SETUPS, selectedId: null, loaded: true });
    localStorage.clear();
  });

  it('says so when nothing is selected, rather than implying a default', () => {
    renderPicker();
    expect(screen.getByRole('button', { name: /no setup/i })).toBeInTheDocument();
  });

  it('shows the market and locked version of the selection', () => {
    useSetupsStore.setState({ selectedId: 'a' });
    renderPicker();

    const trigger = screen.getByRole('button', { name: /BTC 1h Trend/ });
    expect(trigger).toHaveTextContent('BTCUSDT · 1h · 10% × 5× · abc123de');
  });

  it('filters by symbol as well as by name', async () => {
    const user = userEvent.setup();
    renderPicker();

    await user.click(screen.getByRole('button', { name: /no setup/i }));
    await user.type(screen.getByPlaceholderText(/search setups/i), 'ETHUSDT');

    expect(screen.getByRole('option', { name: /ETH 4h Swing/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /BTC 1h Trend/ })).not.toBeInTheDocument();
  });

  it('remembers the selection so every menu header agrees', async () => {
    const user = userEvent.setup();
    renderPicker();

    await user.click(screen.getByRole('button', { name: /no setup/i }));
    await user.click(screen.getByRole('option', { name: /ETH 4h Swing/ }));

    expect(useSetupsStore.getState().selectedId).toBe('b');
    expect(localStorage.getItem('quanta.setup.selected')).toBe('b');
  });

  it('drops a remembered selection that no longer exists', async () => {
    // A setup archived from another tab would otherwise leave every menu
    // header naming rules that are no longer there.
    localStorage.setItem('quanta.setup.selected', 'archived-one');
    mockSetups = SETUPS;

    useSetupsStore.setState({ setups: [], selectedId: null, loaded: false });
    await useSetupsStore.getState().load();

    expect(useSetupsStore.getState().selectedId).toBeNull();
    expect(useSetupsStore.getState().setups).toHaveLength(2);
  });

  it('restores a remembered selection that is still there', async () => {
    localStorage.setItem('quanta.setup.selected', 'b');
    mockSetups = SETUPS;

    useSetupsStore.setState({ setups: [], selectedId: null, loaded: false });
    await useSetupsStore.getState().load();

    expect(useSetupsStore.getState().selectedId).toBe('b');
  });
});
