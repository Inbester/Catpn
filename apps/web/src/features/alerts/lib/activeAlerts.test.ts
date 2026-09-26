import { describe, expect, it } from 'vitest';

import { nextCheck, toRows } from './activeAlerts';
import type { Alert } from './types';

function alert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 'a',
    name: 'BTC over 100',
    source: 'price',
    setup_id: null,
    symbol: 'BTCUSDT',
    interval: '1h',
    condition: { price: 100, direction: 'above' },
    trigger_mode: 'bar_close',
    repeat_mode: 'once_per_bar',
    expires_at: null,
    quiet_from_hour: null,
    quiet_to_hour: null,
    template: '',
    locale: 'en',
    destinations: [],
    enabled: true,
    last_fired_at: null,
    fire_count: 0,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('nextCheck', () => {
  it('lands on the next UTC bar boundary', () => {
    // Bars close on UTC boundaries, so 10:17 on an hourly alert is 11:00.
    const at = Date.UTC(2026, 0, 1, 10, 17);
    const expected = new Date(Date.UTC(2026, 0, 1, 11, 0)).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
    expect(nextCheck('1h', at)).toBe(expected);
  });

  it('says nothing for a timeframe it does not know', () => {
    expect(nextCheck('7s', Date.now())).toBeNull();
  });
});

describe('toRows', () => {
  it('groups an alert without a setup under its market', () => {
    // Otherwise the tray shows a heading of "undefined".
    expect(toRows([alert()])[0]?.setupName).toBe('BTCUSDT · 1h');
  });

  it('groups a setup alert under the alert name', () => {
    expect(toRows([alert({ setup_id: 's1', name: 'BTC Trend' })])[0]?.setupName).toBe('BTC Trend');
  });

  it('describes a price alert as the crossing it is', () => {
    expect(toRows([alert()])[0]?.description).toBe('Price crosses above 100');
  });

  it('says every tick when the alert does not wait for bar close', () => {
    expect(toRows([alert({ trigger_mode: 'tick' })])[0]?.nextCheckAt).toBe('every tick');
  });
});
