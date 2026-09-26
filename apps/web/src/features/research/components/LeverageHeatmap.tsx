/**
 * The margin x leverage surface (SPEC §3.2).
 *
 * Colour carries the return; the border carries the budget. Cells outside
 * the drawdown budget are dimmed rather than hidden, because the shape of
 * the surface past the limit is information — it shows how close the
 * chosen cell sits to the edge.
 *
 * Liquidations are badged, not folded into the colour. A cell that earned
 * well while being liquidated twice is not the same as one that earned
 * the same and never was, and a single number cannot say so.
 */

import type { Cell } from '../lib/types';
import styles from './research.module.css';

export interface LeverageHeatmapProps {
  cells: Cell[];
  budgetPercent: number | null;
  selected?: Cell | null;
  onSelect?: (cell: Cell) => void;
}

/** Diverging tint: red through neutral to green, scaled to the best cell. */
function tint(net: number, strongest: number): string {
  if (strongest <= 0) return 'transparent';
  const share = Math.max(-1, Math.min(1, net / strongest));
  const token = share >= 0 ? 'var(--up)' : 'var(--down)';
  return `color-mix(in srgb, ${token} ${Math.abs(share) * 70}%, transparent)`;
}

export function LeverageHeatmap({
  cells,
  budgetPercent,
  selected,
  onSelect,
}: LeverageHeatmapProps) {
  const margins = [...new Set(cells.map((c) => c.margin_percent))].sort((a, b) => a - b);
  const leverages = [...new Set(cells.map((c) => c.leverage))].sort((a, b) => a - b);
  const strongest = Math.max(...cells.map((c) => Math.abs(c.net_percent)), 1);
  const byKey = new Map(cells.map((c) => [`${c.margin_percent}|${c.leverage}`, c]));

  return (
    <div className={styles.heatmapWrap}>
      <table className={styles.heatmap}>
        <thead>
          <tr>
            <th className={styles.heatCorner}>margin \ leverage</th>
            {leverages.map((leverage) => (
              <th key={leverage}>{leverage}×</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {margins.map((margin) => (
            <tr key={margin}>
              <th>{margin}%</th>
              {leverages.map((leverage) => {
                const cell = byKey.get(`${margin}|${leverage}`);
                if (!cell) return <td key={leverage} />;

                const overBudget =
                  budgetPercent !== null && cell.max_drawdown_percent < budgetPercent;
                const isSelected =
                  selected?.margin_percent === margin && selected.leverage === leverage;

                return (
                  <td key={leverage}>
                    <button
                      type="button"
                      className={`${styles.heatCell} ${overBudget ? styles.heatDim : ''} ${
                        isSelected ? styles.heatPick : ''
                      }`}
                      style={{ background: tint(cell.net_percent, strongest) }}
                      onClick={() => onSelect?.(cell)}
                      title={
                        `${margin}% × ${leverage}× — exposure ${cell.exposure.toFixed(2)}× equity\n` +
                        `net ${cell.net_percent.toFixed(1)}%, ` +
                        `drawdown ${cell.max_drawdown_percent.toFixed(1)}%, ` +
                        `${cell.trades} trades` +
                        (cell.liquidations > 0 ? `, ${cell.liquidations} liquidations` : '') +
                        (overBudget ? '\nPast the drawdown budget.' : '')
                      }
                    >
                      <span className={styles.heatNet}>
                        {cell.net_percent >= 0 ? '+' : ''}
                        {cell.net_percent.toFixed(0)}%
                      </span>
                      <span className={styles.heatDd}>{cell.max_drawdown_percent.toFixed(0)}%</span>
                      {cell.liquidations > 0 ? (
                        <span
                          className={styles.heatLiq}
                          title={`${cell.liquidations} liquidations`}
                        >
                          {cell.liquidations}
                        </span>
                      ) : null}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <p className={styles.legend}>
        Each cell: net return above, max drawdown below. A badge is the number of liquidations.
        {budgetPercent !== null
          ? ` Dimmed cells drew down past your ${budgetPercent.toFixed(0)}% budget.`
          : ''}{' '}
        Exposure is margin × leverage, so cells on the same diagonal control the same amount — the
        cheaper one in leverage has its liquidation price further away.
      </p>
    </div>
  );
}
