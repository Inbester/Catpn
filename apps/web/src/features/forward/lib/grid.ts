/**
 * Parameter ranges for walk-forward (SPEC §3.3).
 *
 * The engine takes an explicit list of values per parameter; the UI offers
 * from/to/step because that is how people think about a sweep. Expanding it
 * here rather than server-side keeps the count visible while it is being
 * edited — a grid that is too large should be obvious before it is run.
 */

/** Matches quanta_engine.forward.walkforward.MAX_COMBINATIONS. */
export const MAX_COMBINATIONS = 400;

export interface ParamRange {
  from: number;
  to: number;
  step: number;
}

/**
 * The values a range covers, inclusive of both ends.
 *
 * Values are computed as `from + i * step` rather than by accumulation, so
 * a step of 0.1 gives 0.3 and not 0.30000000000000004 — a parameter that
 * prints one thing and hashes as another is worse than no sweep at all.
 */
export function expandRange({ from, to, step }: ParamRange): number[] {
  if (!Number.isFinite(from) || !Number.isFinite(to) || !Number.isFinite(step)) return [];
  if (from === to) return [from];
  if (step <= 0) return [];
  if (to < from) return [];

  // Round the count before flooring: (0.3 - 0.1) / 0.1 is 1.9999999999999998,
  // which would silently drop the last value of a range the user wrote.
  const span = (to - from) / step;
  const steps = Math.floor(Number(span.toFixed(9)));
  const decimals = Math.max(decimalsOf(from), decimalsOf(step));

  const values: number[] = [];
  for (let i = 0; i <= steps; i += 1) {
    values.push(round(from + i * step, decimals));
  }
  // Keep the stated end when the step does not divide the span evenly, so a
  // range reads as written instead of stopping short of its own bound.
  const last = values[values.length - 1];
  if (last !== undefined && last < to) values.push(round(to, decimals));
  return values;
}

function decimalsOf(value: number): number {
  const text = String(value);
  const dot = text.indexOf('.');
  return dot === -1 ? 0 : text.length - dot - 1;
}

function round(value: number, decimals: number): number {
  return Number(value.toFixed(Math.min(decimals, 10)));
}

/** How many backtests one in-sample window would run. */
export function combinationCount(grid: Record<string, number[]>): number {
  return Object.values(grid).reduce((total, values) => total * Math.max(values.length, 1), 1);
}

/** Drop parameters that only hold their current value: they are not a search. */
export function prune(grid: Record<string, number[]>): Record<string, number[]> {
  return Object.fromEntries(Object.entries(grid).filter(([, values]) => values.length > 1));
}

/**
 * A range per parameter, each starting fixed at its current value.
 *
 * Starting fixed means opening the tab never silently multiplies the work a
 * run does: a sweep is something you ask for.
 */
export function defaultRanges(params: Record<string, number>): Record<string, ParamRange> {
  return Object.fromEntries(
    Object.entries(params).map(([name, value]) => [
      name,
      { from: value, to: value, step: suggestStep(value) },
    ]),
  );
}

/** A step on the scale of the value itself, so the first edit is usable. */
function suggestStep(value: number): number {
  const magnitude = Math.abs(value);
  if (magnitude === 0) return 1;
  if (Number.isInteger(value)) return magnitude >= 20 ? 5 : 1;
  return magnitude < 1 ? 0.1 : 0.5;
}

export function buildGrid(ranges: Record<string, ParamRange>): Record<string, number[]> {
  return Object.fromEntries(
    Object.entries(ranges).map(([name, range]) => [name, expandRange(range)]),
  );
}
