/**
 * The parameter sweep each in-sample window searches (SPEC §3.3).
 *
 * Without a grid a walk-forward only measures one fixed set of rules
 * across windows; the in-sample leg fits nothing and efficiency —
 * out-of-sample return over in-sample return — has no meaning. The rows
 * here are what turn it into an optimisation.
 *
 * A parameter left at a single value is dropped before the request, so the
 * engine never re-runs identical backtests and never reports a "chosen"
 * value that nothing chose.
 */

import { MAX_COMBINATIONS, buildGrid, combinationCount, type ParamRange } from '../lib/grid';
import styles from './forward.module.css';

export interface ParameterGridProps {
  /** The frozen strategy's parameters, which are what can be swept. */
  params: Record<string, number>;
  ranges: Record<string, ParamRange>;
  onChange: (ranges: Record<string, ParamRange>) => void;
}

export function ParameterGrid({ params, ranges, onChange }: ParameterGridProps) {
  const names = Object.keys(params);

  if (names.length === 0) {
    return (
      <p className={styles.hint}>
        This strategy has no parameters, so there is nothing to sweep. Write one in the Test sidebar
        — <span className="num">fast = 20</span> — and use its name in a rule, and the windows can
        search it.
      </p>
    );
  }

  const grid = buildGrid(ranges);
  const total = combinationCount(grid);
  const empty = names.filter((name) => (grid[name] ?? []).length === 0);
  const searching = names.filter((name) => (grid[name] ?? []).length > 1);

  const edit = (name: string, patch: Partial<ParamRange>) => {
    const current = ranges[name];
    if (!current) return;
    onChange({ ...ranges, [name]: { ...current, ...patch } });
  };

  return (
    <div className={styles.grid}>
      <div className={styles.gridHead}>
        <span>Parameter</span>
        <span>From</span>
        <span>To</span>
        <span>Step</span>
        <span>Values</span>
      </div>

      {names.map((name) => {
        const range = ranges[name];
        const values = grid[name] ?? [];
        if (!range) return null;

        return (
          <div key={name} className={styles.gridRow}>
            <span className={styles.gridName}>{name}</span>
            {(['from', 'to', 'step'] as const).map((field) => (
              <input
                key={field}
                className={styles.gridInput}
                type="number"
                aria-label={`${name} ${field}`}
                value={range[field]}
                onChange={(event) => {
                  const next = Number(event.target.value);
                  if (Number.isFinite(next)) edit(name, { [field]: next });
                }}
              />
            ))}
            <span className={`${styles.gridValues} ${values.length === 0 ? styles.gridBad : ''}`}>
              {values.length === 0
                ? 'no values'
                : values.length === 1
                  ? 'fixed'
                  : `${values.length} · ${describe(values)}`}
            </span>
          </div>
        );
      })}

      <p className={styles.gridTotal}>
        {empty.length > 0 ? (
          <span className={styles.gridBad}>
            {empty.join(', ')} {empty.length === 1 ? 'covers' : 'cover'} no values — check that
            &ldquo;to&rdquo; is past &ldquo;from&rdquo; and the step is above zero.
          </span>
        ) : searching.length === 0 ? (
          <>
            Every parameter is fixed, so the windows measure one set of rules rather than fitting
            them and efficiency stays undefined. Widen a range to search.
          </>
        ) : (
          <>
            <span className={total > MAX_COMBINATIONS ? styles.gridBad : ''}>
              {total.toLocaleString()} combinations
            </span>{' '}
            per window
            {total > MAX_COMBINATIONS
              ? ` — over the ${MAX_COMBINATIONS} an interactive run allows.`
              : '.'}
          </>
        )}
      </p>
    </div>
  );
}

/** The first, second and last values, so a long sweep is still readable. */
function describe(values: number[]): string {
  if (values.length <= 3) return values.join(', ');
  return `${values[0]}, ${values[1]}, …, ${values[values.length - 1]}`;
}
