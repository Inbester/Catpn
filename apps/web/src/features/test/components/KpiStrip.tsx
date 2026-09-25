/**
 * The backtest KPI strip (SPEC §3.3 Overview).
 *
 * Every figure here is after costs. Buy & hold sits alongside on purpose:
 * a strategy that underperforms simply holding the asset is not a strategy,
 * and hiding that comparison would be the easiest way to flatter one.
 */

import { money, percent, ratio, signedMoney } from '../lib/format';
import type { BacktestStats } from '../lib/types';
import styles from './KpiStrip.module.css';

export interface KpiStripProps {
  stats: BacktestStats;
}

interface Cell {
  label: string;
  value: string;
  note: string;
  tone?: 'up' | 'down' | 'neutral';
}

export function KpiStrip({ stats }: KpiStripProps) {
  const costs = stats.total_fees + stats.total_funding;

  const cells: Cell[] = [
    {
      label: 'Net profit',
      value: percent(stats.net_profit_percent),
      note: `${signedMoney(stats.net_profit)} USDT`,
      tone: stats.net_profit >= 0 ? 'up' : 'down',
    },
    {
      label: 'Max drawdown',
      value: `${stats.max_drawdown_percent.toFixed(2)}%`,
      note: `${stats.longest_drawdown_bars} bars underwater`,
      tone: 'down',
    },
    {
      label: 'Profit factor',
      value: ratio(stats.profit_factor),
      note: 'gross win / loss',
    },
    {
      label: 'Win rate',
      value: `${stats.win_rate_percent.toFixed(1)}%`,
      note: `${stats.winning_trades} of ${stats.total_trades} trades`,
    },
    {
      label: 'Avg win / avg loss',
      value:
        stats.average_win !== null && stats.average_loss !== null && stats.average_loss !== 0
          ? Math.abs(stats.average_win / stats.average_loss).toFixed(2)
          : '—',
      note: `${stats.average_win === null ? '—' : money(stats.average_win)} / ${
        stats.average_loss === null ? '—' : money(Math.abs(stats.average_loss))
      }`,
    },
    {
      label: 'Sharpe · Sortino',
      value: ratio(stats.sharpe),
      note: `Sortino ${ratio(stats.sortino)}`,
    },
    {
      label: 'Fees + funding',
      value: signedMoney(-costs),
      note:
        stats.costs_over_gross === null
          ? 'no gross profit'
          : `${(stats.costs_over_gross * 100).toFixed(0)}% of gross profit`,
      tone: 'down',
    },
    {
      label: 'Buy & hold',
      value: percent(stats.buy_and_hold_percent),
      note: 'over the same period',
      tone: stats.buy_and_hold_percent >= 0 ? 'up' : 'down',
    },
  ];

  return (
    <div className={styles.strip}>
      {cells.map((cell) => (
        <div key={cell.label} className={styles.cell}>
          <div className={styles.label}>{cell.label}</div>
          <div
            className={`${styles.value} ${
              cell.tone === 'up' ? 'up' : cell.tone === 'down' ? 'down' : ''
            }`}
          >
            {cell.value}
          </div>
          <div className={styles.note}>{cell.note}</div>
        </div>
      ))}
    </div>
  );
}
