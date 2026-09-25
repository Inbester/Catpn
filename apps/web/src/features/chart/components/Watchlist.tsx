/**
 * The right panel: watchlist with instant search and the symbol detail card
 * (SPEC §3.1).
 *
 * Search filters the already-loaded list in memory, so it responds on the
 * keystroke rather than waiting on a round trip.
 */

import { useMemo, useState } from 'react';

import { Icon } from '@/components/Icon';
import type { Ticker } from '../lib/types';
import styles from './Watchlist.module.css';

export interface WatchlistProps {
  tickers: Ticker[];
  activeSymbol: string;
  onSelect: (symbol: string) => void;
  searchRef?: React.MutableRefObject<HTMLInputElement | null> | undefined;
}

function formatPrice(raw: string): string {
  const value = Number(raw);
  if (!Number.isFinite(value)) return raw;
  const digits = value >= 1000 ? 1 : value >= 1 ? 2 : 5;
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatPercent(raw: string): string {
  const value = Number(raw);
  if (!Number.isFinite(value)) return raw;
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
}

function formatCompact(raw: string | null): string {
  if (raw === null) return '—';
  const value = Number(raw);
  if (!Number.isFinite(value)) return raw;
  return value.toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 2 });
}

function formatCountdown(nextFundingTime: number | null): string {
  if (nextFundingTime === null) return '—';
  const remaining = Math.max(0, nextFundingTime - Date.now());
  const hours = Math.floor(remaining / 3_600_000);
  const minutes = Math.floor((remaining % 3_600_000) / 60_000);
  const seconds = Math.floor((remaining % 60_000) / 1000);
  return [hours, minutes, seconds].map((n) => String(n).padStart(2, '0')).join(':');
}

/** Split a symbol so the matched prefix can be underlined. */
function highlight(symbol: string, query: string): React.ReactNode {
  if (!query) return symbol;
  const index = symbol.toUpperCase().indexOf(query.toUpperCase());
  if (index === -1) return symbol;
  return (
    <>
      {symbol.slice(0, index)}
      <mark className={styles.match}>{symbol.slice(index, index + query.length)}</mark>
      {symbol.slice(index + query.length)}
    </>
  );
}

export function Watchlist({ tickers, activeSymbol, onSelect, searchRef }: WatchlistProps) {
  const [tab, setTab] = useState<'watchlist' | 'objects'>('watchlist');
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    if (!query.trim()) return tickers;
    const needle = query.trim().toUpperCase();
    return tickers.filter((ticker) => ticker.symbol.includes(needle));
  }, [tickers, query]);

  const active = tickers.find((ticker) => ticker.symbol === activeSymbol);

  return (
    <aside className={styles.panel}>
      <div className={styles.header}>
        <button
          type="button"
          className={`${styles.tab} ${tab === 'watchlist' ? styles.active : ''}`}
          onClick={() => {
            setTab('watchlist');
          }}
        >
          Watchlist
        </button>
        <button
          type="button"
          className={`${styles.tab} ${tab === 'objects' ? styles.active : ''}`}
          onClick={() => {
            setTab('objects');
          }}
        >
          Objects
        </button>
        <span className={styles.headerSpacer} />
      </div>

      {tab === 'watchlist' ? (
        <>
          <div className={styles.search}>
            <Icon name="search" size={16} />
            <input
              ref={searchRef}
              className={styles.searchInput}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
              }}
              placeholder="Search symbol"
              aria-label="Search symbol"
            />
            <span className={styles.kbd}>⌘K</span>
          </div>

          <div className={styles.columns}>
            <span>Symbol</span>
            <span>Last</span>
            <span>24h</span>
          </div>

          <div className={styles.list}>
            {filtered.length === 0 ? (
              <p className={styles.empty}>No symbols match “{query}”.</p>
            ) : (
              filtered.map((ticker) => {
                const change = Number(ticker.change_percent_24h);
                const base = ticker.symbol.replace(/USDT$/, '');
                return (
                  <button
                    key={ticker.symbol}
                    type="button"
                    className={`${styles.row} ${
                      ticker.symbol === activeSymbol ? styles.active : ''
                    }`}
                    onClick={() => {
                      onSelect(ticker.symbol);
                    }}
                  >
                    <span>
                      <span className={styles.base}>{highlight(base, query)}</span>
                      <span className={styles.quote}>USDT</span>
                    </span>
                    <span className="num">{formatPrice(ticker.last)}</span>
                    <span className={`num ${change >= 0 ? 'up' : 'down'}`}>
                      {formatPercent(ticker.change_percent_24h)}
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </>
      ) : (
        <div className={styles.list}>
          <p className={styles.empty}>
            Drawings on this chart appear here. Select one to edit or remove it.
          </p>
        </div>
      )}

      {active ? (
        <div className={styles.card}>
          <h4 className={styles.cardTitle}>
            {active.symbol} <span>Perpetual</span>
          </h4>
          <div className={styles.field}>
            <i>Mark price</i>
            <em>{active.mark_price ? formatPrice(active.mark_price) : '—'}</em>
          </div>
          <div className={styles.field}>
            <i>Index price</i>
            <em>{active.index_price ? formatPrice(active.index_price) : '—'}</em>
          </div>
          <div className={styles.field}>
            <i>Funding / 8h</i>
            <em className={Number(active.funding_rate ?? 0) >= 0 ? 'up' : 'down'}>
              {active.funding_rate ? `${(Number(active.funding_rate) * 100).toFixed(4)}%` : '—'}
            </em>
          </div>
          <div className={styles.field}>
            <i>Next funding</i>
            <em>{formatCountdown(active.next_funding_time)}</em>
          </div>
          <div className={styles.field}>
            <i>24h high</i>
            <em>{active.high_24h ? formatPrice(active.high_24h) : '—'}</em>
          </div>
          <div className={styles.field}>
            <i>24h low</i>
            <em>{active.low_24h ? formatPrice(active.low_24h) : '—'}</em>
          </div>
          <div className={styles.field}>
            <i>24h volume</i>
            <em>{formatCompact(active.quote_volume_24h)}</em>
          </div>
          <div className={styles.field}>
            <i>Open interest</i>
            <em>{formatCompact(active.open_interest)}</em>
          </div>
        </div>
      ) : null}
    </aside>
  );
}
