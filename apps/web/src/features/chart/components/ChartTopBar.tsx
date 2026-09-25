/**
 * The chart's top bar: symbol, timeframes, chart type, indicators
 * (SPEC §3.1).
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Icon } from '@/components/Icon';
import {
  CHART_TYPES,
  INTERVALS,
  QUICK_INTERVALS,
  type ChartType,
  type Interval,
} from '../lib/types';
import styles from './ChartTopBar.module.css';

const CHART_TYPE_LABELS: Record<ChartType, string> = {
  candles: 'Candles',
  hollow: 'Hollow candles',
  'heikin-ashi': 'Heikin-Ashi',
  bars: 'Bars',
  line: 'Line',
  area: 'Area',
};

export interface ChartTopBarProps {
  symbol: string;
  interval: Interval;
  chartType: ChartType;
  live: boolean;
  onOpenSymbolSearch: () => void;
  onIntervalChange: (interval: Interval) => void;
  onChartTypeChange: (type: ChartType) => void;
  onOpenIndicators: () => void;
  onOpenSettings: () => void;
}

export function ChartTopBar({
  symbol,
  interval,
  chartType,
  live,
  onOpenSymbolSearch,
  onIntervalChange,
  onChartTypeChange,
  onOpenIndicators,
  onOpenSettings,
}: ChartTopBarProps) {
  const { t } = useTranslation();
  const [openMenu, setOpenMenu] = useState<'interval' | 'type' | null>(null);

  const close = () => {
    setOpenMenu(null);
  };

  return (
    <div className={styles.bar}>
      <button type="button" className={styles.symbolButton} onClick={onOpenSymbolSearch}>
        <Icon name="search" size={16} />
        <span className={styles.symbolName}>{symbol}</span>
        <span className={styles.symbolKind}>Perp</span>
      </button>

      <div className={styles.segment}>
        {QUICK_INTERVALS.map((value) => (
          <button
            key={value}
            type="button"
            className={`${styles.segmentItem} ${interval === value ? styles.active : ''}`}
            onClick={() => {
              onIntervalChange(value);
            }}
          >
            {value}
          </button>
        ))}

        <div className={styles.menuWrap}>
          <button
            type="button"
            className={styles.segmentItem}
            aria-label="More timeframes"
            onClick={() => {
              setOpenMenu(openMenu === 'interval' ? null : 'interval');
            }}
          >
            ⌄
          </button>
          {openMenu === 'interval' ? (
            <div className={styles.menu} role="menu">
              {INTERVALS.map((value) => (
                <button
                  key={value}
                  type="button"
                  role="menuitem"
                  className={`${styles.menuItem} ${interval === value ? styles.active : ''}`}
                  onClick={() => {
                    onIntervalChange(value);
                    close();
                  }}
                >
                  {value}
                  {interval === value ? <Icon name="check" size={14} /> : null}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className={styles.menuWrap}>
        <button
          type="button"
          className={styles.button}
          onClick={() => {
            setOpenMenu(openMenu === 'type' ? null : 'type');
          }}
        >
          <Icon name="chart" size={16} />
          {CHART_TYPE_LABELS[chartType]}
        </button>
        {openMenu === 'type' ? (
          <div className={styles.menu} role="menu">
            {CHART_TYPES.map((value) => (
              <button
                key={value}
                type="button"
                role="menuitem"
                className={`${styles.menuItem} ${chartType === value ? styles.active : ''}`}
                onClick={() => {
                  onChartTypeChange(value);
                  close();
                }}
              >
                {CHART_TYPE_LABELS[value]}
                {chartType === value ? <Icon name="check" size={14} /> : null}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <button type="button" className={styles.button} onClick={onOpenIndicators}>
        <Icon name="research" size={16} />
        Indicators
      </button>

      <div className={styles.spacer} />

      <span className={styles.live} title={live ? 'Streaming' : 'Reconnecting'}>
        <span className={`${styles.liveDot} ${live ? '' : styles.stale}`} />
        {live ? 'Live' : 'Offline'}
      </span>

      <button
        type="button"
        className={styles.iconButton}
        onClick={onOpenSettings}
        aria-label={t('nav.settings')}
      >
        <Icon name="settings" size={18} />
      </button>
    </div>
  );
}
