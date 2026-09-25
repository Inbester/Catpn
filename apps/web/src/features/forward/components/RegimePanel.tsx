/**
 * Why the result changed (SPEC §3.3).
 *
 * Each metric is shown as a pair of bars so the two periods can be
 * compared at a glance. The bars are scaled against the larger of the two,
 * not an absolute maximum, because the question is which period was more
 * of something — not how either compares to an arbitrary ceiling.
 */

import type { PeriodSummary } from '../lib/types';
import styles from './forward.module.css';

export interface RegimePanelProps {
  reference: PeriodSummary;
  test: PeriodSummary;
  reading: string;
}

interface Measure {
  label: string;
  reference: number;
  test: number;
  format: (value: number) => string;
}

export function RegimePanel({ reference, test, reading }: RegimePanelProps) {
  const percent = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;
  const money = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(0)}`;

  const measures: Measure[] = [
    {
      label: 'Price over period',
      reference: reference.regime.return_percent,
      test: test.regime.return_percent,
      format: percent,
    },
    {
      label: 'Volatility (annualised)',
      reference: reference.regime.volatility_annual_percent,
      test: test.regime.volatility_annual_percent,
      format: (v) => `${v.toFixed(0)}%`,
    },
    {
      label: 'Trend efficiency',
      reference: reference.regime.trend_efficiency,
      test: test.regime.trend_efficiency,
      format: (v) => v.toFixed(3),
    },
    {
      label: 'Avg candle range',
      reference: reference.regime.average_candle_range_percent,
      test: test.regime.average_candle_range_percent,
      format: (v) => `${v.toFixed(2)}%`,
    },
    {
      label: 'Net from longs',
      reference: Number(reference.stats['long_net_pnl'] ?? 0),
      test: Number(test.stats['long_net_pnl'] ?? 0),
      format: money,
    },
    {
      label: 'Net from shorts',
      reference: Number(reference.stats['short_net_pnl'] ?? 0),
      test: Number(test.stats['short_net_pnl'] ?? 0),
      format: money,
    },
  ];

  return (
    <section className={styles.panel}>
      <header className={styles.panelHeader}>
        <span className={styles.panelTitle}>Market regime</span>
        <span className={styles.panelNote}>why the result changed</span>
      </header>

      <div className={styles.regimeGrid}>
        {measures.map((measure) => {
          const scale = Math.max(Math.abs(measure.reference), Math.abs(measure.test), 1e-9);
          const width = (value: number) => `${(Math.abs(value) / scale) * 100}%`;

          return (
            <div key={measure.label} className={styles.regimeCell}>
              <div className={styles.regimeLabel}>{measure.label}</div>

              <div className={styles.regimeRow}>
                <span className={styles.regimePeriod}>{reference.label}</span>
                <span className={styles.regimeBar}>
                  <span
                    className={styles.regimeFill}
                    style={{ width: width(measure.reference), background: 'var(--muted)' }}
                  />
                </span>
                <span className={styles.regimeValue}>{measure.format(measure.reference)}</span>
              </div>

              <div className={styles.regimeRow}>
                <span className={styles.regimePeriod}>{test.label}</span>
                <span className={styles.regimeBar}>
                  <span
                    className={styles.regimeFill}
                    style={{ width: width(measure.test), background: 'var(--drawing)' }}
                  />
                </span>
                <span className={styles.regimeValue}>{measure.format(measure.test)}</span>
              </div>
            </div>
          );
        })}
      </div>

      <p className={styles.reading}>
        <strong>Reading:</strong> {reading}
      </p>
    </section>
  );
}
