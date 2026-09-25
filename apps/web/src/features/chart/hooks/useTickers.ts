/** Watchlist quotes, polled. */

import { useEffect, useState } from 'react';

import { api } from '@/lib/api/client';
import type { Ticker } from '../lib/types';

const POLL_MS = 5000;

export function useTickers(): { tickers: Ticker[]; error: string | null } {
  const [tickers, setTickers] = useState<Ticker[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = () => {
      api
        .get<Ticker[]>('/market/tickers')
        .then((rows) => {
          if (!cancelled) {
            setTickers(rows);
            setError(null);
          }
        })
        .catch((caught: unknown) => {
          if (!cancelled) {
            setError(caught instanceof Error ? caught.message : 'Could not load quotes.');
          }
        });
    };

    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return { tickers, error };
}
