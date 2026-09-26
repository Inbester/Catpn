/**
 * How far each trade went underwater before it closed (SPEC §3.2).
 *
 * The x axis is the worst the trade got; the y axis is where it ended.
 * The interesting region is up and to the right — winners that were
 * deeply red first. Those are the trades leverage takes away: the
 * liquidation lines show which of them a given leverage would have closed
 * out before they recovered.
 */

import type { TradePoint } from '../lib/types';
import styles from './research.module.css';

export interface MaeScatterProps {
  points: TradePoint[];
  /** Leverages to draw liquidation lines for. */
  leverages?: number[];
  height?: number;
}

const MAINTENANCE = 0.004;

export function MaeScatter({ points, leverages = [5, 10, 25], height = 320 }: MaeScatterProps) {
  if (points.length === 0) {
    return <p className={styles.empty}>No trades to plot.</p>;
  }

  const maxAdverse = Math.max(...points.map((p) => p.adverse_percent), 1);
  const results = points.map((p) => p.result_percent);
  const maxResult = Math.max(...results, 1);
  const minResult = Math.min(...results, -1);
  const span = maxResult - minResult || 1;

  const x = (adverse: number) => (adverse / maxAdverse) * 100;
  const y = (result: number) => ((maxResult - result) / span) * 100;

  return (
    <div className={styles.scatter} style={{ height }}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className={styles.scatterSvg}>
        {/* Break-even: everything above this line ended green. */}
        <line
          x1="0"
          x2="100"
          y1={y(0)}
          y2={y(0)}
          className={styles.scatterZero}
          vectorEffect="non-scaling-stroke"
        />
        {leverages.map((leverage) => {
          const dip = (1 / leverage - MAINTENANCE) * 100;
          if (dip <= 0 || dip > maxAdverse) return null;
          return (
            <line
              key={leverage}
              x1={x(dip)}
              x2={x(dip)}
              y1="0"
              y2="100"
              className={styles.scatterLiq}
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
        {points.map((point) => (
          <circle
            key={point.index}
            cx={x(point.adverse_percent)}
            cy={y(point.result_percent)}
            r="1.2"
            className={
              point.was_liquidated
                ? styles.dotLiquidated
                : point.result_percent >= 0
                  ? styles.dotWin
                  : styles.dotLoss
            }
          />
        ))}
      </svg>

      <div className={styles.scatterAxes}>
        {leverages.map((leverage) => {
          const dip = (1 / leverage - MAINTENANCE) * 100;
          if (dip <= 0 || dip > maxAdverse) return null;
          return (
            <span
              key={leverage}
              className={styles.scatterTick}
              style={{ insetInlineStart: `${x(dip)}%` }}
            >
              {leverage}× liquidates
            </span>
          );
        })}
      </div>

      <div className={styles.scatterLabels}>
        <span>worst dip while open, % of margin →</span>
        <span className="num">{maxAdverse.toFixed(0)}%</span>
      </div>
    </div>
  );
}
