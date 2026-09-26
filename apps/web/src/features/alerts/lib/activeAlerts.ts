/**
 * The rail's active-alerts bell (SPEC §2).
 *
 * The bell was built in phase 0 with nothing behind it. This fills it
 * from the alerts that are actually enabled, grouped by the Setup they
 * act through, with the next bar close each one will be evaluated on.
 *
 * Polled slowly. An alert's state changes when the user changes it, not
 * on its own, so a fast poll would cost requests to tell us nothing.
 */

import { create } from 'zustand';

import * as alertsApi from './api';
import type { Alert } from './types';

const POLL_MS = 30_000;

export interface ActiveAlertRow {
  id: string;
  setupName: string;
  description: string;
  nextCheckAt: string | null;
}

interface ActiveAlertsState {
  alerts: Alert[];
  load: () => Promise<void>;
}

export const useActiveAlerts = create<ActiveAlertsState>((set) => ({
  alerts: [],
  load: async () => {
    const alerts = await alertsApi.listAlerts(true);
    set({ alerts });
  },
}));

const INTERVAL_MS: Record<string, number> = {
  '1m': 60_000,
  '5m': 300_000,
  '15m': 900_000,
  '30m': 1_800_000,
  '1h': 3_600_000,
  '4h': 14_400_000,
  '1d': 86_400_000,
};

/** When this alert's timeframe next closes a bar, in the local clock. */
export function nextCheck(interval: string, now: number = Date.now()): string | null {
  const step = INTERVAL_MS[interval];
  if (step === undefined) return null;
  // Bars close on UTC boundaries, so the next one is the next multiple.
  const next = Math.floor(now / step) * step + step;
  return new Date(next).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/** A condition value as text. Conditions are free-form JSON, so an
 *  unexpected shape becomes empty rather than "[object Object]". */
function plain(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

export function toRows(alerts: Alert[], now: number = Date.now()): ActiveAlertRow[] {
  return alerts.map((alert) => ({
    id: alert.id,
    // Alerts without a Setup are grouped under their market instead, so
    // the tray never shows a heading of "undefined".
    setupName: alert.setup_id ? alert.name : `${alert.symbol} · ${alert.interval}`,
    description:
      alert.source === 'price'
        ? `Price crosses ${plain(alert.condition['direction'])} ${plain(alert.condition['price'])}`
        : `${alert.source} · ${alert.symbol} ${alert.interval}`,
    nextCheckAt: alert.trigger_mode === 'bar_close' ? nextCheck(alert.interval, now) : 'every tick',
  }));
}

/** Start polling for the bell. Returns a stop function. */
export function watchActiveAlerts(): () => void {
  const tick = () => {
    void useActiveAlerts
      .getState()
      .load()
      .catch(() => {
        // The bell is not worth surfacing an error for.
      });
  };
  tick();
  const timer = setInterval(tick, POLL_MS);
  return () => {
    clearInterval(timer);
  };
}
