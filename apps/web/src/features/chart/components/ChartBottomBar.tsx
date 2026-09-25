/**
 * The chart's bottom bar: range buttons, the clock with its timezone, and
 * the price-scale modes (SPEC §3.1).
 */

import { useEffect, useState } from 'react';

import { RANGES, type PriceScaleMode, type RangeKey } from '../lib/ranges';
import styles from './ChartBottomBar.module.css';

export interface ChartBottomBarProps {
  timezone: string;
  priceScaleMode: PriceScaleMode;
  onRangeSelect: (range: RangeKey) => void;
  onPriceScaleModeChange: (mode: PriceScaleMode) => void;
  onResetView: () => void;
}

function useClock(timezone: string): string {
  const [label, setLabel] = useState('');

  useEffect(() => {
    const tick = () => {
      try {
        setLabel(
          new Intl.DateTimeFormat('en-GB', {
            timeZone: timezone,
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
          }).format(new Date()),
        );
      } catch {
        // An unknown timezone should not blank the bar.
        setLabel(new Date().toISOString().slice(11, 19));
      }
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => {
      clearInterval(timer);
    };
  }, [timezone]);

  return label;
}

export function ChartBottomBar({
  timezone,
  priceScaleMode,
  onRangeSelect,
  onPriceScaleModeChange,
  onResetView,
}: ChartBottomBarProps) {
  const clock = useClock(timezone);

  return (
    <div className={styles.bar}>
      {RANGES.map((range) => (
        <button
          key={range}
          type="button"
          className={styles.range}
          onClick={() => {
            onRangeSelect(range);
          }}
        >
          {range}
        </button>
      ))}

      <span className={styles.divider} />

      <button type="button" className={styles.range} onClick={onResetView}>
        Go to latest
      </button>

      <span className={styles.spacer} />

      <span className={styles.clock}>{clock}</span>
      <span>{timezone}</span>

      <span className={styles.divider} />

      <button
        type="button"
        className={`${styles.mode} ${priceScaleMode === 'percentage' ? styles.active : ''}`}
        onClick={() => {
          onPriceScaleModeChange(priceScaleMode === 'percentage' ? 'normal' : 'percentage');
        }}
        title="Percentage scale"
      >
        %
      </button>
      <button
        type="button"
        className={`${styles.mode} ${priceScaleMode === 'logarithmic' ? styles.active : ''}`}
        onClick={() => {
          onPriceScaleModeChange(priceScaleMode === 'logarithmic' ? 'normal' : 'logarithmic');
        }}
        title="Logarithmic scale"
      >
        log
      </button>
      <button
        type="button"
        className={`${styles.mode} ${priceScaleMode === 'normal' ? styles.active : ''}`}
        onClick={() => {
          onPriceScaleModeChange('normal');
        }}
        title="Auto scale"
      >
        auto
      </button>
    </div>
  );
}
