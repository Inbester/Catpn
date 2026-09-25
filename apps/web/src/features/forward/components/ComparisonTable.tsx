/**
 * The side-by-side metric table, with the Monte Carlo band beside each
 * figure that has one.
 *
 * The band is the point: a number that fell inside the range the strategy
 * could plausibly have produced is a different fact from one that did not,
 * and the change column alone cannot say which.
 */

import type { MetricRow } from '../lib/types';
import styles from './forward.module.css';

export interface ComparisonTableProps {
  metrics: MetricRow[];
  referenceLabel: string;
  testLabel: string;
}

function formatValue(row: MetricRow, value: number): string {
  if (row.unit === '%') return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  if (row.unit === 'd') return `${value.toFixed(1)} d`;
  if (row.key === 'trades' || row.key === 'liquidations') return String(Math.round(value));
  if (row.key === 'costs') return value.toFixed(2);
  return value.toFixed(2);
}

function formatChange(row: MetricRow): string {
  const change = row.change;
  const sign = change >= 0 ? '+' : '';
  if (row.unit === '%') return `${sign}${change.toFixed(2)} pt`;
  if (row.unit === 'd') return `${sign}${change.toFixed(1)} d`;
  if (row.key === 'trades' || row.key === 'liquidations') {
    return `${sign}${Math.round(change)}`;
  }
  return `${sign}${change.toFixed(2)}`;
}

/** Green when the change went the way the user wants, red when it did not. */
function changeTone(row: MetricRow): string {
  if (row.change === 0) return '';
  const good = row.higher_is_better ? row.change > 0 : row.change < 0;
  return good ? 'up' : 'down';
}

export function ComparisonTable({ metrics, referenceLabel, testLabel }: ComparisonTableProps) {
  return (
    <section className={styles.panel}>
      <header className={styles.panelHeader}>
        <span className={styles.panelTitle}>Side by side</span>
        <span className={styles.panelNote}>same version, same costs</span>
      </header>

      <div className={`${styles.panelBody} ${styles.tableScroll}`}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Metric</th>
              <th>
                <span className={styles.swatch} style={{ background: 'var(--muted)' }} />
                {referenceLabel}
              </th>
              <th>
                <span className={styles.swatch} style={{ background: 'var(--drawing)' }} />
                {testLabel}
              </th>
              <th>Change</th>
              <th>Expected range</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((row) => (
              <tr key={row.key}>
                <td className={styles.metricLabel}>{row.label}</td>
                <td>{formatValue(row, row.reference)}</td>
                <td>{formatValue(row, row.test)}</td>
                <td className={changeTone(row)}>{formatChange(row)}</td>
                <td>
                  {row.band ? (
                    <span className={styles.band}>
                      <span className={styles.bandRange}>
                        {row.band.low.toFixed(1)} … {row.band.high.toFixed(1)}
                      </span>
                      <span className={styles.bandTrack}>
                        <span
                          className={`${styles.bandMarker} ${
                            row.band.contains ? '' : styles.bandMarkerOut
                          }`}
                          style={{ left: `${row.band.position * 100}%` }}
                        />
                      </span>
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
