/**
 * The list of trades (SPEC §3.3), with run-up, drawdown, fees and funding
 * per row and the cumulative equity it left behind.
 */

import { useMemo, useState } from 'react';

import { money, price, signedMoney, timestamp } from '../lib/format';
import { EXIT_REASON_LABELS, type Trade } from '../lib/types';
import styles from './panels.module.css';

export interface TradesTableProps {
  trades: Trade[];
  timezone?: string;
  onSelect?: (trade: Trade) => void;
}

type SortKey = 'entry_time' | 'net_pnl' | 'bars_held' | 'drawdown';

export function TradesTable({ trades, timezone = 'UTC', onSelect }: TradesTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('entry_time');
  const [descending, setDescending] = useState(false);

  const sorted = useMemo(() => {
    const copy = trades.slice();
    copy.sort((a, b) => {
      const delta = a[sortKey] - b[sortKey];
      return descending ? -delta : delta;
    });
    return copy;
  }, [trades, sortKey, descending]);

  const toggle = (key: SortKey) => {
    if (key === sortKey) {
      setDescending((value) => !value);
    } else {
      setSortKey(key);
      setDescending(key !== 'entry_time');
    }
  };

  if (trades.length === 0) {
    return (
      <div className={styles.panel}>
        <p className={styles.empty}>This strategy did not take a trade over the selected range.</p>
      </div>
    );
  }

  const header = (key: SortKey, label: string) => (
    <th>
      <button
        type="button"
        onClick={() => {
          toggle(key);
        }}
        style={{ color: sortKey === key ? 'var(--text)' : 'inherit', font: 'inherit' }}
      >
        {label}
        {sortKey === key ? (descending ? ' ↓' : ' ↑') : ''}
      </button>
    </th>
  );

  return (
    <div className={styles.panel}>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Side</th>
              {header('entry_time', 'Entry')}
              <th>Price</th>
              <th>Exit</th>
              <th>Price</th>
              <th>Reason</th>
              {header('bars_held', 'Bars')}
              <th>Run-up</th>
              {header('drawdown', 'Drawdown')}
              <th>Fees</th>
              <th>Funding</th>
              {header('net_pnl', 'Net P&L')}
              <th>Equity</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((trade, index) => (
              <tr
                key={`${trade.entry_time}-${index}`}
                onClick={() => onSelect?.(trade)}
                style={onSelect ? { cursor: 'pointer' } : undefined}
              >
                <td className={`${styles.side} ${trade.side === 'long' ? 'up' : 'down'}`}>
                  {trade.side === 'long' ? 'Long' : 'Short'}
                </td>
                <td>{timestamp(trade.entry_time, timezone)}</td>
                <td>{price(trade.entry_price)}</td>
                <td>{timestamp(trade.exit_time, timezone)}</td>
                <td>{price(trade.exit_price)}</td>
                <td
                  className={`${styles.reason} ${
                    trade.exit_reason === 'liquidation' ? 'down' : ''
                  }`}
                >
                  {EXIT_REASON_LABELS[trade.exit_reason] ?? trade.exit_reason}
                </td>
                <td>{trade.bars_held}</td>
                <td className="up">{money(trade.run_up)}</td>
                <td className="down">{money(trade.drawdown)}</td>
                <td className="down">{money(-trade.fees)}</td>
                <td className={trade.funding >= 0 ? 'down' : 'up'}>{money(-trade.funding)}</td>
                <td className={trade.net_pnl >= 0 ? 'up' : 'down'}>{signedMoney(trade.net_pnl)}</td>
                <td>{money(trade.equity_after)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
