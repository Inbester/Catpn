/**
 * Walk-forward results (SPEC §3.3).
 *
 * The chained curve is the only equity curve in the product that was not
 * produced by hindsight, so it gets the same drawdown pane as every other
 * equity chart — the rule holds especially here.
 */

import { EquityChart } from '@/features/test/components/EquityChart';
import { ratio } from '@/features/test/lib/format';
import type { WalkForwardResult } from '../lib/types';
import styles from './forward.module.css';

export interface WalkForwardPanelProps {
  result: WalkForwardResult;
  timezone?: string;
}

function day(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

export function WalkForwardPanel({ result }: WalkForwardPanelProps) {
  const span = result.windows.length
    ? {
        start: Math.min(...result.windows.map((w) => w.in_sample_start)),
        end: Math.max(...result.windows.map((w) => w.out_of_sample_end)),
      }
    : null;

  return (
    <>
      <section className={styles.panel}>
        <header className={styles.panelHeader}>
          <span className={styles.panelTitle}>Out-of-sample equity</span>
          <span className={styles.panelNote}>
            {result.total_net_percent >= 0 ? '+' : ''}
            {result.total_net_percent.toFixed(2)}% · max drawdown{' '}
            {result.max_drawdown_percent.toFixed(2)}% · {result.total_trades} trades · efficiency{' '}
            {ratio(result.walk_forward_efficiency)}
          </span>
        </header>
        <div className={styles.panelBody}>
          {result.chained.time.length > 0 ? (
            <EquityChart
              time={result.chained.time}
              equity={result.chained.value}
              drawdown={result.chained.drawdown}
              height={300}
            />
          ) : (
            <p className="muted">No out-of-sample trades were taken.</p>
          )}
        </div>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelHeader}>
          <span className={styles.panelTitle}>Windows</span>
          <span className={styles.legend}>
            <span className={styles.legendItem}>
              <span className={styles.swatch} style={{ background: 'var(--dim)' }} />
              in sample
            </span>
            <span className={styles.legendItem}>
              <span className={styles.swatch} style={{ background: 'var(--drawing)' }} />
              tested on
            </span>
          </span>
        </header>

        <div className={styles.panelBody}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>#</th>
                <th>Timeline</th>
                <th>Chosen parameters</th>
                <th>In-sample</th>
                <th>Out-of-sample</th>
                <th>Max DD</th>
                <th>Trades</th>
                <th>Efficiency</th>
              </tr>
            </thead>
            <tbody>
              {result.windows.map((window) => {
                const total = span ? span.end - span.start : 1;
                const lead = span ? ((window.in_sample_start - span.start) / total) * 100 : 0;
                const inWidth = ((window.in_sample_end - window.in_sample_start) / total) * 100;
                const outWidth =
                  ((window.out_of_sample_end - window.out_of_sample_start) / total) * 100;

                return (
                  <tr key={window.index}>
                    <td className={styles.metricLabel}>{window.index + 1}</td>
                    <td style={{ minWidth: 200 }}>
                      <span
                        className={styles.windowBar}
                        title={
                          `optimised ${day(window.in_sample_start)}–${day(window.in_sample_end)}, ` +
                          `tested ${day(window.out_of_sample_start)}–${day(window.out_of_sample_end)}`
                        }
                      >
                        <span style={{ width: `${lead}%` }} />
                        <span className={styles.windowIn} style={{ width: `${inWidth}%` }} />
                        <span className={styles.windowOut} style={{ width: `${outWidth}%` }} />
                      </span>
                    </td>
                    <td className={styles.metricLabel}>
                      {Object.entries(window.chosen_params)
                        .map(([name, value]) => `${name}=${value}`)
                        .join(' ')}
                      {window.note ? <span className="muted"> · {window.note}</span> : null}
                    </td>
                    <td className={window.in_sample_net_percent >= 0 ? 'up' : 'down'}>
                      {window.in_sample_net_percent >= 0 ? '+' : ''}
                      {window.in_sample_net_percent.toFixed(2)}%
                    </td>
                    <td className={window.out_of_sample_net_percent >= 0 ? 'up' : 'down'}>
                      {window.out_of_sample_net_percent >= 0 ? '+' : ''}
                      {window.out_of_sample_net_percent.toFixed(2)}%
                    </td>
                    <td className="down">{window.out_of_sample_max_drawdown.toFixed(2)}%</td>
                    <td>{window.out_of_sample_trades}</td>
                    <td>{ratio(window.efficiency)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
