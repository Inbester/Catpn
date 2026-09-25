/**
 * Bars for one series: a REST load, then live updates over the WebSocket.
 *
 * The socket only ever rewrites the newest bar or appends a new one, so a
 * late frame cannot rewrite settled history — the same rule the server
 * enforces when it stores them.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, getAccessToken, API_PREFIX } from '@/lib/api/client';
import type { Bar, Interval, KlineResponse, PriceType, StreamMessage } from '../lib/types';
import { toBar } from '../lib/types';

export interface UseKlinesResult {
  bars: Bar[];
  loading: boolean;
  error: string | null;
  /** True while the live socket is connected. */
  live: boolean;
  reload: () => void;
}

const DEFAULT_LIMIT = 1500;

function websocketUrl(symbol: string, interval: Interval, token: string): string {
  const base = window.location.origin.replace(/^http/, 'ws');
  const params = new URLSearchParams({ token, symbol, interval });
  return `${base}${API_PREFIX}/market/stream?${params.toString()}`;
}

/** Merge a streamed bar into the series, in place of the last one or after it. */
export function applyBar(bars: Bar[], incoming: Bar): Bar[] {
  if (bars.length === 0) return [incoming];

  const last = bars[bars.length - 1] as Bar;

  if (incoming.time === last.time) {
    // The forming bar ticked. A closed bar is never reopened.
    if (last.closed && !incoming.closed) return bars;
    const next = bars.slice();
    next[next.length - 1] = incoming;
    return next;
  }

  if (incoming.time > last.time) return [...bars, incoming];

  // Older than what we hold: only accept it if it fills the exact slot.
  const index = bars.findIndex((bar) => bar.time === incoming.time);
  if (index === -1) return bars;
  const next = bars.slice();
  next[index] = incoming;
  return next;
}

export function useKlines(
  symbol: string,
  interval: Interval,
  priceType: PriceType = 'LAST',
): UseKlinesResult {
  const [bars, setBars] = useState<Bar[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  const socketRef = useRef<WebSocket | null>(null);

  const reload = useCallback(() => {
    setReloadToken((value) => value + 1);
  }, []);

  // --- Initial history ---------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const params = new URLSearchParams({
      symbol,
      interval,
      limit: String(DEFAULT_LIMIT),
      price_type: priceType,
    });

    api
      .get<KlineResponse>(`/market/klines?${params.toString()}`)
      .then((response) => {
        if (cancelled) return;
        setBars(response.bars.map(toBar));
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setError(caught instanceof Error ? caught.message : 'Could not load bars.');
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [symbol, interval, priceType, reloadToken]);

  // --- Live updates ------------------------------------------------------
  useEffect(() => {
    const token = getAccessToken();
    if (!token) return undefined;

    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;

    const connect = () => {
      if (closed) return;

      const socket = new WebSocket(websocketUrl(symbol, interval, token));
      socketRef.current = socket;

      socket.onopen = () => {
        attempt = 0;
        setLive(true);
      };

      socket.onmessage = (event: MessageEvent<string>) => {
        let message: StreamMessage;
        try {
          message = JSON.parse(event.data) as StreamMessage;
        } catch {
          return;
        }
        if (message.type !== 'kline' || !message.bar) return;
        // Frames for another series can arrive while switching timeframe.
        if (message.interval && message.interval !== interval) return;
        if (message.symbol !== symbol) return;

        setBars((current) => applyBar(current, toBar(message.bar as never)));
      };

      socket.onclose = () => {
        setLive(false);
        if (closed) return;
        attempt += 1;
        // Back off, with a cap, so a server restart does not spin the tab.
        const delay = Math.min(10_000, 500 * 2 ** Math.min(attempt, 4));
        retry = setTimeout(connect, delay);
      };

      socket.onerror = () => {
        socket.close();
      };
    };

    connect();

    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      setLive(false);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [symbol, interval]);

  return { bars, loading, error, live, reload };
}
