/**
 * Equity with its drawdown pane underneath.
 *
 * DECISIONS makes this a rule, not a preference: every equity chart in the
 * product carries a drawdown pane. A rising curve alone hides how much the
 * strategy asked the trader to sit through, which is the part that decides
 * whether it can actually be run.
 */

import { useEffect, useRef } from 'react';
import {
  AreaSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type UTCTimestamp,
} from 'lightweight-charts';

import { chartOptions, readPalette } from '@/features/chart/lib/chartTheme';

export interface EquityChartProps {
  time: number[];
  equity: number[];
  drawdown: number[];
  /** Buy & hold on the same axis, for the honest comparison. */
  benchmark?: number[] | undefined;
  height?: number;
}

const asTime = (ms: number) => (ms / 1000) as UTCTimestamp;

export function EquityChart({ time, equity, drawdown, benchmark, height = 320 }: EquityChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || time.length === 0) return undefined;

    const palette = readPalette();
    const chart = createChart(container, {
      ...chartOptions(palette),
      height,
      timeScale: { borderColor: palette.line, timeVisible: false, rightOffset: 0 },
    });
    chartRef.current = chart;

    const equitySeries = chart.addSeries(AreaSeries, {
      lineColor: palette.text,
      topColor: `${palette.text}22`,
      bottomColor: `${palette.text}02`,
      lineWidth: 2,
      priceLineVisible: false,
    });
    equitySeries.setData(time.map((t, i) => ({ time: asTime(t), value: equity[i] ?? 0 })));

    if (benchmark && benchmark.length === time.length) {
      const benchmarkSeries = chart.addSeries(LineSeries, {
        color: palette.muted,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      benchmarkSeries.setData(time.map((t, i) => ({ time: asTime(t), value: benchmark[i] ?? 0 })));
    }

    // Pane 1 is the drawdown, always present.
    const drawdownSeries = chart.addSeries(
      AreaSeries,
      {
        lineColor: palette.down,
        topColor: `${palette.down}00`,
        bottomColor: `${palette.down}55`,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        invertFilledArea: true,
      },
      1,
    );
    drawdownSeries.setData(time.map((t, i) => ({ time: asTime(t), value: drawdown[i] ?? 0 })));

    const panes = chart.panes();
    if (panes.length > 1) {
      // Give the drawdown roughly a quarter of the height.
      panes[0]?.setHeight(Math.round(height * 0.72));
      panes[1]?.setHeight(Math.round(height * 0.28));
    }

    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [time, equity, drawdown, benchmark, height]);

  if (time.length === 0) {
    return null;
  }

  return <div ref={containerRef} style={{ width: '100%', height }} />;
}
