/** Range buttons under the chart (SPEC §3.1). */

export const RANGES = ['1D', '5D', '1M', '3M', '6M', 'YTD', '1Y', 'All'] as const;
export type RangeKey = (typeof RANGES)[number];

export type PriceScaleMode = 'normal' | 'logarithmic' | 'percentage';

/**
 * How many bars a range covers at a given timeframe.
 *
 * `null` means "everything", which the caller turns into fitContent().
 */
export function barsForRange(range: RangeKey, intervalSeconds: number): number | null {
  if (range === 'All') return null;

  if (range === 'YTD') {
    const start = Date.UTC(new Date().getUTCFullYear(), 0, 1);
    return Math.ceil((Date.now() - start) / 1000 / intervalSeconds);
  }

  const seconds: Partial<Record<RangeKey, number>> = {
    '1D': 86_400,
    '5D': 432_000,
    '1M': 2_592_000,
    '3M': 7_776_000,
    '6M': 15_552_000,
    '1Y': 31_536_000,
  };
  const span = seconds[range];
  return span ? Math.ceil(span / intervalSeconds) : null;
}
