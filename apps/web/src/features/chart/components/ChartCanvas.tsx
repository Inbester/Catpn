/**
 * The Lightweight Charts surface: price pane plus one pane per non-overlay
 * indicator.
 *
 * Series are created once and updated in place; recreating them on every
 * render would reset the user's zoom and pan on every live tick.
 */

import { useEffect, useRef } from 'react';
import {
  AreaSeries,
  BarSeries,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';

import { heikinAshi } from '../lib/indicators';
import { INDICATORS, type IndicatorInstance } from '../lib/indicatorRegistry';
import { candleOptions, chartOptions, readPalette } from '../lib/chartTheme';
import type { Bar, ChartType } from '../lib/types';

export interface ChartCanvasProps {
  bars: Bar[];
  chartType: ChartType;
  indicators: IndicatorInstance[];
  /** 'normal' | 'logarithmic' | 'percentage' on the price scale. */
  priceScaleMode: 'normal' | 'logarithmic' | 'percentage';
  onCrosshairMove?: (bar: Bar | null) => void;
  /**
   * Called once the chart exists and again whenever the price series is
   * rebuilt, so the drawing layer always holds a live series to convert
   * prices through.
   */
  onReady?: (chart: IChartApi, series: ISeriesApi<'Candlestick' | 'Bar' | 'Line' | 'Area'>) => void;
}

const asTime = (ms: number) => (ms / 1000) as UTCTimestamp;

export function ChartCanvas({
  bars,
  chartType,
  indicators,
  priceScaleMode,
  onCrosshairMove,
  onReady,
}: ChartCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const priceSeriesRef = useRef<ISeriesApi<'Candlestick' | 'Bar' | 'Line' | 'Area'> | null>(null);
  // Keyed by `${indicator.key}:${lineIndex}` so a line survives re-renders.
  const overlayRef = useRef(new Map<string, ISeriesApi<'Line' | 'Histogram'>>());
  const paneRef = useRef(new Map<string, number>());
  const barsRef = useRef<Bar[]>([]);
  const onCrosshairRef = useRef(onCrosshairMove);
  const onReadyRef = useRef(onReady);

  onCrosshairRef.current = onCrosshairMove;
  onReadyRef.current = onReady;
  barsRef.current = bars;

  // --- Create the chart once --------------------------------------------
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const palette = readPalette();
    const chart = createChart(container, chartOptions(palette));
    chartRef.current = chart;

    // Captured here so cleanup clears the same maps this effect created.
    const overlays = overlayRef.current;
    const panes = paneRef.current;

    const handler = (param: { time?: unknown; point?: unknown }) => {
      const callback = onCrosshairRef.current;
      if (!callback) return;
      if (param.time === undefined || param.point === undefined) {
        callback(null);
        return;
      }
      const seconds = Number(param.time);
      callback(barsRef.current.find((bar) => bar.time / 1000 === seconds) ?? null);
    };
    chart.subscribeCrosshairMove(handler);

    return () => {
      chart.unsubscribeCrosshairMove(handler);
      chart.remove();
      chartRef.current = null;
      priceSeriesRef.current = null;
      overlays.clear();
      panes.clear();
    };
    // Created once for the component's lifetime.
  }, []);

  // --- Price series: recreated only when the chart type changes ---------
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    if (priceSeriesRef.current) {
      chart.removeSeries(priceSeriesRef.current);
      priceSeriesRef.current = null;
    }

    const palette = readPalette();

    if (chartType === 'line' || chartType === 'area') {
      priceSeriesRef.current = chart.addSeries(
        chartType === 'line' ? LineSeries : AreaSeries,
        chartType === 'line'
          ? { color: palette.series1, lineWidth: 2 }
          : {
              lineColor: palette.up,
              topColor: `${palette.up}44`,
              bottomColor: `${palette.up}05`,
              lineWidth: 2,
            },
      );
    } else if (chartType === 'bars') {
      priceSeriesRef.current = chart.addSeries(BarSeries, {
        upColor: palette.up,
        downColor: palette.down,
      });
    } else {
      priceSeriesRef.current = chart.addSeries(
        CandlestickSeries,
        candleOptions(palette, chartType === 'hollow'),
      );
    }

    if (priceSeriesRef.current) onReadyRef.current?.(chart, priceSeriesRef.current);
  }, [chartType]);

  // --- Price scale mode --------------------------------------------------
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    // 0 normal, 1 logarithmic, 2 percentage in the library's enum.
    const mode = priceScaleMode === 'logarithmic' ? 1 : priceScaleMode === 'percentage' ? 2 : 0;
    chart.priceScale('right').applyOptions({ mode });
  }, [priceScaleMode]);

  // --- Price data --------------------------------------------------------
  useEffect(() => {
    const series = priceSeriesRef.current;
    if (!series || bars.length === 0) return;

    const source = chartType === 'heikin-ashi' ? heikinAshi(bars) : bars;

    if (chartType === 'line' || chartType === 'area') {
      series.setData(source.map((bar) => ({ time: asTime(bar.time), value: bar.close })));
    } else {
      series.setData(
        source.map((bar) => ({
          time: asTime(bar.time),
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        })),
      );
    }
  }, [bars, chartType]);

  // --- Indicators --------------------------------------------------------
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || bars.length === 0) return;

    const palette = readPalette();
    const wanted = new Set<string>();
    let nextPane = 1;

    for (const instance of indicators) {
      const definition = INDICATORS[instance.id];
      if (!definition) continue;

      // Non-overlay indicators each get their own pane, in order.
      let paneIndex = 0;
      if (!definition.overlay) {
        paneIndex = paneRef.current.get(instance.key) ?? nextPane;
        paneRef.current.set(instance.key, paneIndex);
        nextPane = Math.max(nextPane, paneIndex) + 1;
      }

      const lines = definition.compute(bars, instance.params, palette);

      lines.forEach((line, index) => {
        const key = `${instance.key}:${index}`;
        wanted.add(key);

        let series = overlayRef.current.get(key);
        if (!series) {
          series = line.histogram
            ? chart.addSeries(
                HistogramSeries,
                { color: line.color, priceLineVisible: false, lastValueVisible: false },
                paneIndex,
              )
            : chart.addSeries(
                LineSeries,
                {
                  color: line.color,
                  lineWidth: line.lineWidth ?? 1,
                  priceLineVisible: false,
                  lastValueVisible: !definition.overlay && index === lines.length - 1,
                  crosshairMarkerVisible: false,
                },
                paneIndex,
              );
          overlayRef.current.set(key, series);

          // Reference levels: RSI 30/70, MACD zero.
          if (index === 0 && definition.levels) {
            for (const level of definition.levels) {
              series.createPriceLine({
                price: level,
                color: palette.dim,
                lineWidth: 1,
                lineStyle: LineStyle.Dotted,
                axisLabelVisible: true,
                title: '',
              });
            }
          }
        }

        series.applyOptions({ visible: instance.visible });

        const data = bars.flatMap((bar, i) => {
          const value = line.values[i];
          if (value === null || value === undefined) return [];
          // Volume takes the bar's own direction; other histograms take sign.
          const color =
            line.histogram && instance.id === 'volume'
              ? `${bar.close >= bar.open ? palette.up : palette.down}44`
              : line.histogram
                ? value >= 0
                  ? palette.up
                  : palette.down
                : undefined;
          return [{ time: asTime(bar.time), value, ...(color ? { color } : {}) }];
        });
        series.setData(data);
      });
    }

    // Drop series for indicators that were removed.
    for (const [key, series] of overlayRef.current) {
      if (!wanted.has(key)) {
        chart.removeSeries(series);
        overlayRef.current.delete(key);
      }
    }
  }, [bars, indicators]);

  return <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />;
}
