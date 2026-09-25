/**
 * The chart legend: OHLC with change, a live dot, and each indicator's
 * current value. Hovering an indicator reveals eye / gear / × (SPEC §3.1).
 *
 * Values follow the crosshair when it is over a bar, and fall back to the
 * latest bar otherwise — which is what the mockup shows at rest.
 */

import { useMemo } from 'react';

import { Icon } from '@/components/Icon';
import { INDICATORS, type IndicatorInstance } from '../lib/indicatorRegistry';
import { readPalette } from '../lib/chartTheme';
import type { Bar, Interval } from '../lib/types';
import styles from './Legend.module.css';

export interface LegendProps {
  symbol: string;
  interval: Interval;
  bars: Bar[];
  hovered: Bar | null;
  live: boolean;
  indicators: IndicatorInstance[];
  /**
   * Which indicators this legend shows. The price pane carries the OHLC row
   * and the overlays; each extra pane carries its own indicator, matching
   * the approved design.
   */
  variant?: 'price' | 'pane';
  /** Distance from the top of the chart, for a pane legend. */
  offsetTop?: number;
  onToggleIndicator: (key: string) => void;
  onRemoveIndicator: (key: string) => void;
  onConfigureIndicator: (key: string) => void;
}

function formatPrice(value: number): string {
  // Keep small-cap prices readable without padding BTC with noise.
  const digits = value >= 1000 ? 1 : value >= 1 ? 2 : 6;
  return value.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatCompact(value: number): string {
  return value.toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 2 });
}

export function Legend({
  symbol,
  interval,
  bars,
  hovered,
  live,
  indicators,
  variant = 'price',
  offsetTop,
  onToggleIndicator,
  onRemoveIndicator,
  onConfigureIndicator,
}: LegendProps) {
  const palette = useMemo(() => readPalette(), []);
  const bar = hovered ?? bars[bars.length - 1] ?? null;
  const index = bar ? bars.findIndex((candidate) => candidate.time === bar.time) : -1;

  const change = bar ? bar.close - bar.open : 0;
  const changePercent = bar && bar.open !== 0 ? (change / bar.open) * 100 : 0;
  const up = change >= 0;

  return (
    <div
      className={styles.legend}
      style={offsetTop === undefined ? undefined : { top: `${offsetTop}px` }}
    >
      {variant === 'price' ? (
        <div className={styles.row}>
          <span className={`${styles.liveDot} ${live ? '' : styles.stale}`} />
          <span className={styles.title}>
            {symbol} · {interval} · Bitunix
          </span>
          {bar ? (
            <span className={`${styles.ohlc} num`}>
              <span>
                O <span className={styles.value}>{formatPrice(bar.open)}</span>
              </span>
              <span>
                H <span className={styles.value}>{formatPrice(bar.high)}</span>
              </span>
              <span>
                L <span className={styles.value}>{formatPrice(bar.low)}</span>
              </span>
              <span>
                C <span className={up ? 'up' : 'down'}>{formatPrice(bar.close)}</span>
              </span>
              <span className={up ? 'up' : 'down'}>
                {up ? '+' : ''}
                {formatPrice(change)} ({up ? '+' : ''}
                {changePercent.toFixed(2)}%)
              </span>
            </span>
          ) : null}
        </div>
      ) : null}

      {indicators.map((instance) => {
        const definition = INDICATORS[instance.id];
        if (!definition) return null;

        const lines =
          index >= 0 && bars.length > 0 ? definition.compute(bars, instance.params, palette) : [];

        return (
          <div
            key={instance.key}
            className={`${styles.indicatorRow} ${instance.visible ? '' : styles.hidden}`}
          >
            <span className={styles.indicatorName}>{definition.label(instance.params)}</span>

            {lines.map((line, lineIndex) => {
              const value = index >= 0 ? line.values[index] : null;
              return (
                <span key={`${instance.key}-${lineIndex}`} className={styles.indicatorRow}>
                  <span className={styles.swatch} style={{ background: line.color }} />
                  <span className={`${styles.value} num`}>
                    {value === null || value === undefined
                      ? '—'
                      : instance.id === 'volume'
                        ? formatCompact(value)
                        : formatPrice(value)}
                  </span>
                </span>
              );
            })}

            <span className={styles.controls}>
              <button
                type="button"
                className={styles.control}
                onClick={() => {
                  onToggleIndicator(instance.key);
                }}
                aria-label={instance.visible ? 'Hide' : 'Show'}
                title={instance.visible ? 'Hide' : 'Show'}
              >
                <Icon name={instance.visible ? 'eye' : 'eyeOff'} size={12} />
              </button>
              <button
                type="button"
                className={styles.control}
                onClick={() => {
                  onConfigureIndicator(instance.key);
                }}
                aria-label="Settings"
                title="Settings"
              >
                <Icon name="settings" size={12} />
              </button>
              <button
                type="button"
                className={styles.control}
                onClick={() => {
                  onRemoveIndicator(instance.key);
                }}
                aria-label="Remove"
                title="Remove"
              >
                <Icon name="close" size={12} />
              </button>
            </span>
          </div>
        );
      })}
    </div>
  );
}
