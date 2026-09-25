/**
 * The candle countdown, pinned under the last-price tag on the price scale
 * (SPEC §3.1).
 *
 * Its vertical position follows the last price through the series' own
 * scale, so it stays attached as the chart scrolls and rescales rather than
 * floating at a fixed offset.
 */

import { useEffect, useState } from 'react';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';

import styles from './PriceCountdown.module.css';

export interface PriceCountdownProps {
  chart: IChartApi | null;
  series: ISeriesApi<'Candlestick' | 'Bar' | 'Line' | 'Area'> | null;
  lastPrice: number | null;
  label: string;
  up: boolean;
}

export function PriceCountdown({ chart, series, lastPrice, label, up }: PriceCountdownProps) {
  const [top, setTop] = useState<number | null>(null);

  useEffect(() => {
    if (!chart || !series || lastPrice === null) {
      setTop(null);
      return undefined;
    }

    const update = () => {
      const y = series.priceToCoordinate(lastPrice);
      setTop(y === null ? null : y);
    };

    update();
    const timeScale = chart.timeScale();
    timeScale.subscribeVisibleLogicalRangeChange(update);

    // The price scale can move without the time scale doing so (a live tick
    // pushing the range), so poll at a rate that stays invisible.
    const timer = setInterval(update, 250);

    return () => {
      timeScale.unsubscribeVisibleLogicalRangeChange(update);
      clearInterval(timer);
    };
  }, [chart, series, lastPrice]);

  if (top === null || !label) return null;

  return (
    <span
      className={`${styles.countdown} ${up ? styles.up : styles.down}`}
      // Offset by roughly one tag height so it sits under the price label.
      style={{ top: `${top + 12}px` }}
      aria-label="Time left in this candle"
    >
      {label}
    </span>
  );
}
