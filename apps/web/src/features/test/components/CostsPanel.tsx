/**
 * Where the gross result actually went (SPEC §3.3 cost breakdown).
 *
 * Costs are broken out rather than netted away because they are what most
 * strategies lose to: a gross-positive edge that pays it all back in fees
 * and funding is a losing strategy, and the only way to see that is to
 * show the lines separately.
 */

import { money, signedMoney } from '../lib/format';
import type { BacktestStats, Trade } from '../lib/types';
import styles from './panels.module.css';

export interface CostsPanelProps {
  stats: BacktestStats;
  trades: Trade[];
}

export function CostsPanel({ stats, trades }: CostsPanelProps) {
  // Funding is signed per trade: longs usually pay, shorts usually receive.
  const fundingPaid = trades.reduce((sum, t) => sum + Math.max(0, t.funding), 0);
  const fundingReceived = trades.reduce((sum, t) => sum + Math.min(0, t.funding), 0);

  const longWins = trades.filter((t) => t.side === 'long' && t.net_pnl > 0).length;
  const shortWins = trades.filter((t) => t.side === 'short' && t.net_pnl > 0).length;

  const rate = (wins: number, total: number) =>
    total === 0 ? '—' : `${((wins / total) * 100).toFixed(1)}`;

  return (
    <>
      <section className={styles.panel}>
        <header className={styles.panelHeader}>
          <span className={styles.panelTitle}>Costs breakdown</span>
          <span className={styles.panelNote}>USDT</span>
        </header>
        <div className={styles.panelBody}>
          <div className={styles.rows}>
            <div className={styles.row}>
              <span className={styles.rowLabel}>Gross P&amp;L</span>
              <span className={`${styles.rowValue} ${stats.gross_profit >= 0 ? 'up' : 'down'}`}>
                {signedMoney(stats.gross_profit)}
              </span>
            </div>
            <div className={styles.row}>
              <span className={styles.rowLabel}>Trading fees</span>
              <span className={`${styles.rowValue} down`}>{signedMoney(-stats.total_fees)}</span>
            </div>
            <div className={styles.row}>
              <span className={styles.rowLabel}>Funding paid</span>
              <span className={`${styles.rowValue} down`}>{signedMoney(-fundingPaid)}</span>
            </div>
            <div className={styles.row}>
              <span className={styles.rowLabel}>Funding received</span>
              <span className={`${styles.rowValue} up`}>{signedMoney(-fundingReceived)}</span>
            </div>
            <div className={`${styles.row} ${styles.total}`}>
              <span>Net P&amp;L</span>
              <span className={`${styles.rowValue} ${stats.net_profit >= 0 ? 'up' : 'down'}`}>
                {signedMoney(stats.net_profit)}
              </span>
            </div>
          </div>
        </div>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelHeader}>
          <span className={styles.panelTitle}>Long vs short</span>
          {stats.liquidations > 0 ? (
            <span className={`${styles.panelNote} down`}>
              {stats.liquidations} liquidation{stats.liquidations === 1 ? '' : 's'}
            </span>
          ) : null}
        </header>
        <div className={styles.panelBody}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Side</th>
                <th>Trades</th>
                <th>Win %</th>
                <th>Net</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Long</td>
                <td>{stats.long_trades}</td>
                <td>{rate(longWins, stats.long_trades)}</td>
                <td className={stats.long_net_pnl >= 0 ? 'up' : 'down'}>
                  {signedMoney(stats.long_net_pnl)}
                </td>
              </tr>
              <tr>
                <td>Short</td>
                <td>{stats.short_trades}</td>
                <td>{rate(shortWins, stats.short_trades)}</td>
                <td className={stats.short_net_pnl >= 0 ? 'up' : 'down'}>
                  {signedMoney(stats.short_net_pnl)}
                </td>
              </tr>
            </tbody>
          </table>
          <div className={styles.rows} style={{ marginTop: 'var(--space-4)' }}>
            <div className={styles.row}>
              <span className={styles.rowLabel}>Largest win</span>
              <span className={`${styles.rowValue} up`}>{signedMoney(stats.largest_win)}</span>
            </div>
            <div className={styles.row}>
              <span className={styles.rowLabel}>Largest loss</span>
              <span className={`${styles.rowValue} down`}>{signedMoney(stats.largest_loss)}</span>
            </div>
            <div className={styles.row}>
              <span className={styles.rowLabel}>Average bars held</span>
              <span className={styles.rowValue}>
                {stats.average_bars_held === null ? '—' : money(stats.average_bars_held, 1)}
              </span>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
