/**
 * Time left in the forming bar.
 *
 * SPEC §3.1: the countdown uses exchange server time and UTC bar
 * boundaries, not the browser clock, which can be minutes off. The offset
 * between the two is measured once and reapplied every tick.
 */

import { useEffect, useState } from 'react';

import { api } from '@/lib/api/client';
import { INTERVAL_SECONDS, type Interval } from '../lib/types';

/** Format for the countdown, by how long the bar is (SPEC §3.1). */
export function formatCountdown(secondsLeft: number, intervalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(secondsLeft));

  if (intervalSeconds >= 86_400) {
    const days = Math.floor(seconds / 86_400);
    const hours = Math.floor((seconds % 86_400) / 3600);
    return `${days}d ${String(hours).padStart(2, '0')}h`;
  }

  if (intervalSeconds >= 3600) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const rest = seconds % 60;
    return [hours, minutes, rest].map((n) => String(n).padStart(2, '0')).join(':');
  }

  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

/** Seconds until the bar containing `nowMs` closes. */
export function secondsUntilClose(nowMs: number, intervalSeconds: number): number {
  const step = intervalSeconds * 1000;
  const openTime = Math.floor(nowMs / step) * step;
  return (openTime + step - nowMs) / 1000;
}

export function useCountdown(interval: Interval): string {
  const [offsetMs, setOffsetMs] = useState(0);
  const [label, setLabel] = useState('');

  // Measure the browser's drift from server time once per mount.
  useEffect(() => {
    let cancelled = false;
    const sentAt = Date.now();

    api
      .get<{ server_time: number }>('/market/time')
      .then((response) => {
        if (cancelled) return;
        // Assume a symmetric round trip and split it.
        const latency = (Date.now() - sentAt) / 2;
        setOffsetMs(response.server_time + latency - Date.now());
      })
      .catch(() => {
        // Fall back to the browser clock rather than showing nothing.
        if (!cancelled) setOffsetMs(0);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const seconds = INTERVAL_SECONDS[interval];

    const tick = () => {
      setLabel(formatCountdown(secondsUntilClose(Date.now() + offsetMs, seconds), seconds));
    };

    tick();
    const timer = setInterval(tick, 1000);
    return () => {
      clearInterval(timer);
    };
  }, [interval, offsetMs]);

  return label;
}
