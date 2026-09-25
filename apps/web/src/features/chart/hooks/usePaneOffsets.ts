/**
 * Where each chart pane starts, in pixels from the top of the chart.
 *
 * Pane legends are HTML overlaid on the canvas, so they need the same
 * geometry the chart uses internally. Reading it from the chart rather than
 * assuming fixed heights means the legends stay put when the user resizes
 * a pane.
 */

import { useEffect, useState } from 'react';
import type { IChartApi } from 'lightweight-charts';

export function usePaneOffsets(chart: IChartApi | null, paneCount: number): number[] {
  const [offsets, setOffsets] = useState<number[]>([]);

  useEffect(() => {
    if (!chart) {
      setOffsets([]);
      return undefined;
    }

    const measure = () => {
      try {
        const panes = chart.panes();
        const result: number[] = [];
        let top = 0;
        for (const pane of panes) {
          result.push(top);
          // Panes are separated by a 1px divider the API does not report.
          top += pane.getHeight() + 1;
        }
        setOffsets(result);
      } catch {
        // A chart mid-teardown can throw; an empty list just hides legends.
        setOffsets([]);
      }
    };

    measure();
    // Pane heights change on resize and when a pane is added or removed.
    const timer = setInterval(measure, 500);
    return () => {
      clearInterval(timer);
    };
  }, [chart, paneCount]);

  return offsets;
}
