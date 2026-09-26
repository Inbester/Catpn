/**
 * The Forward test tabs: period vs period and walk-forward (SPEC §3.3).
 *
 * The strategy version is frozen for the whole panel — both periods, every
 * window. That is what makes the comparison about the data rather than
 * about two different sets of rules.
 */

import { useState } from 'react';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import type { BacktestConfig } from '@/features/test/lib/types';
import { EquityChart } from '@/features/test/components/EquityChart';
import { ComparisonTable } from './components/ComparisonTable';
import { ParameterGrid } from './components/ParameterGrid';
import { RegimePanel } from './components/RegimePanel';
import { VerdictCard } from './components/VerdictCard';
import { WalkForwardPanel } from './components/WalkForwardPanel';
import * as forwardApi from './lib/api';
import {
  MAX_COMBINATIONS,
  buildGrid,
  combinationCount,
  defaultRanges,
  prune,
  type ParamRange,
} from './lib/grid';
import {
  MONTH_NAMES,
  PRESETS,
  currentMonth,
  customPeriods,
  presetMonths,
  type CalendarMonth,
  type Period,
  type PresetKey,
} from './lib/presets';
import type { ComparisonResult, WalkForwardResult } from './lib/types';
import styles from './ForwardPanel.module.css';

export interface ForwardPanelProps {
  strategyId: string | null;
  strategyVersion: string | null;
  symbol: string;
  interval: string;
  config: BacktestConfig;
  /** The frozen strategy's parameters — what a walk-forward can sweep. */
  params?: Record<string, number>;
}

type Tab = 'periods' | 'walkforward';

export function ForwardPanel({
  strategyId,
  strategyVersion,
  symbol,
  interval,
  config,
  params = {},
}: ForwardPanelProps) {
  const [tab, setTab] = useState<Tab>('periods');
  const [preset, setPreset] = useState<PresetKey | null>('same_month_last_year');
  // The two months are the source of truth; a preset only sets them,
  // so editing one afterwards is the same operation as picking a preset.
  const [months, setMonths] = useState<MonthPair>(() => presetMonths('same_month_last_year'));
  const periods = customPeriods(months.reference, months.test);

  const [ranges, setRanges] = useState<Record<string, ParamRange>>(() => defaultRanges(params));
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [walkForward, setWalkForward] = useState<WalkForwardResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const choosePreset = (key: PresetKey) => {
    setPreset(key);
    setMonths(presetMonths(key));
    setComparison(null);
  };

  const editMonth = (side: 'reference' | 'test', patch: Partial<CalendarMonth>) => {
    setPreset(null);
    setMonths((current) => ({ ...current, [side]: { ...current[side], ...patch } }));
    setComparison(null);
  };

  const runComparison = async () => {
    if (!strategyId) return;
    setBusy(true);
    setError(null);
    try {
      setComparison(
        await forwardApi.comparePeriods(strategyId, {
          symbol,
          interval,
          reference: periods.reference,
          test: periods.test,
          config,
          monte_carlo_runs: 3000,
        }),
      );
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The comparison could not run.');
    } finally {
      setBusy(false);
    }
  };

  const grid = prune(buildGrid(ranges));
  const combinations = combinationCount(grid);
  const gridTooLarge = combinations > MAX_COMBINATIONS;

  const runWalkForward = async () => {
    if (!strategyId) return;
    setBusy(true);
    setError(null);
    try {
      setWalkForward(
        await forwardApi.runWalkForward(strategyId, {
          symbol,
          interval,
          in_sample_days: 90,
          out_of_sample_days: 30,
          max_windows: 12,
          grid,
          config,
        }),
      );
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The walk-forward could not run.');
    } finally {
      setBusy(false);
    }
  };

  if (!strategyId) {
    return (
      <div className={styles.placeholder}>
        Save a strategy first. A forward test runs one frozen version across different data, so it
        needs a version to freeze.
      </div>
    );
  }

  const ordered = periods.reference.start < periods.test.start;

  const describe = (period: Period) =>
    `${new Date(period.start).toISOString().slice(0, 10)} – ${new Date(period.end)
      .toISOString()
      .slice(0, 10)}`;

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <nav className={styles.tabs}>
          <button
            type="button"
            className={`${styles.tab} ${tab === 'periods' ? styles.active : ''}`}
            onClick={() => {
              setTab('periods');
            }}
          >
            Period vs period
          </button>
          <button
            type="button"
            className={`${styles.tab} ${tab === 'walkforward' ? styles.active : ''}`}
            onClick={() => {
              setTab('walkforward');
            }}
          >
            Walk-forward
          </button>
        </nav>

        <span className={styles.spacer} />

        {strategyVersion ? (
          <span className={styles.frozen} title="Both periods use this exact version">
            <Icon name="lock" size={12} />
            {strategyVersion.slice(0, 12)} · parameters frozen
          </span>
        ) : null}
      </div>

      {tab === 'periods' ? (
        <>
          <div className={styles.controls}>
            <div className={styles.presets}>
              {PRESETS.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  className={`${styles.preset} ${preset === option.key ? styles.active : ''}`}
                  onClick={() => {
                    choosePreset(option.key);
                  }}
                  title={option.description}
                >
                  {option.label}
                </button>
              ))}
            </div>

            <div className={styles.periods}>
              <div className={styles.period}>
                <span className={styles.periodLabel}>Reference</span>
                <MonthPicker
                  value={months.reference}
                  onChange={(patch) => {
                    editMonth('reference', patch);
                  }}
                />
                <span className={styles.periodRange}>{describe(periods.reference)}</span>
              </div>
              <Icon name="test" size={16} className={styles.arrow} />
              <div className={`${styles.period} ${styles.periodTest}`}>
                <span className={styles.periodLabel}>Test on · unseen data</span>
                <MonthPicker
                  value={months.test}
                  onChange={(patch) => {
                    editMonth('test', patch);
                  }}
                />
                <span className={styles.periodRange}>{describe(periods.test)}</span>
              </div>
            </div>

            {ordered ? null : (
              <p className={styles.warn} role="status">
                The reference month is not older than the test month. A forward test asks whether
                what held before still holds later, so this pair reads backwards.
              </p>
            )}

            <button
              type="button"
              className={styles.run}
              onClick={() => {
                void runComparison();
              }}
              disabled={busy}
            >
              {busy ? 'Running…' : 'Run forward test'}
            </button>
          </div>

          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}

          {comparison ? (
            <div className={styles.results}>
              <VerdictCard
                verdict={comparison.verdict}
                headline={comparison.headline}
                explanation={comparison.explanation}
                checks={comparison.checks}
              />

              <div className={styles.split}>
                <ComparisonTable
                  metrics={comparison.metrics}
                  referenceLabel={comparison.reference.label}
                  testLabel={comparison.test.label}
                />

                <section className={styles.chartPanel}>
                  <div className={styles.chartTitle}>Equity, with drawdown underneath</div>
                  <EquityChart
                    time={comparison.test.equity_by_trade.map((_, i) => i * 86_400_000)}
                    equity={comparison.test.equity_by_trade}
                    drawdown={comparison.test.equity_by_trade.map((value, i, all) => {
                      const peak = Math.max(...all.slice(0, i + 1));
                      return peak > 0 ? value - peak : Math.min(0, value);
                    })}
                    height={320}
                  />
                  <div className={styles.chartNote}>
                    By trade number. Expected 90% range: {comparison.monte_carlo.net.low.toFixed(1)}
                    % to {comparison.monte_carlo.net.high.toFixed(1)}% over{' '}
                    {comparison.monte_carlo.runs.toLocaleString()} runs.
                  </div>
                </section>
              </div>

              <RegimePanel
                reference={comparison.reference}
                test={comparison.test}
                reading={comparison.reading}
              />
            </div>
          ) : null}
        </>
      ) : (
        <>
          <div className={styles.controls}>
            <p className={styles.hint}>
              Twelve windows: 90 days in sample, the 30 days after them tested. Each window picks
              its parameters on the in-sample stretch alone, then trades them forward. The chained
              curve uses only data each window had not seen.
            </p>

            <ParameterGrid params={params} ranges={ranges} onChange={setRanges} />

            <button
              type="button"
              className={styles.run}
              onClick={() => {
                void runWalkForward();
              }}
              disabled={busy || gridTooLarge}
              title={
                gridTooLarge
                  ? `${combinations.toLocaleString()} combinations per window is over the interactive limit.`
                  : undefined
              }
            >
              {busy ? 'Running…' : 'Run walk-forward'}
            </button>
          </div>

          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}

          {walkForward ? (
            <div className={styles.results}>
              <WalkForwardPanel result={walkForward} />
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

interface MonthPair {
  reference: CalendarMonth;
  test: CalendarMonth;
}

const YEAR_SPAN = 8;

function MonthPicker({
  value,
  onChange,
}: {
  value: CalendarMonth;
  onChange: (patch: Partial<CalendarMonth>) => void;
}) {
  const thisYear = currentMonth().year;
  const years = Array.from({ length: YEAR_SPAN }, (_, i) => thisYear - (YEAR_SPAN - 1) + i);
  // A preset can reach further back than the list; keep that year selectable.
  if (!years.includes(value.year)) years.unshift(value.year);

  return (
    <div className={styles.picker}>
      <select
        className={styles.pickerField}
        value={value.month}
        aria-label="Month"
        onChange={(event) => {
          onChange({ month: Number(event.target.value) });
        }}
      >
        {MONTH_NAMES.map((name, index) => (
          <option key={name} value={index + 1}>
            {name}
          </option>
        ))}
      </select>
      <select
        className={styles.pickerField}
        value={value.year}
        aria-label="Year"
        onChange={(event) => {
          onChange({ year: Number(event.target.value) });
        }}
      >
        {years.map((year) => (
          <option key={year} value={year}>
            {year}
          </option>
        ))}
      </select>
    </div>
  );
}
