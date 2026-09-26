/**
 * The Test menu (SPEC §3.3): edit a strategy, run a backtest against
 * stored bars, and read the result.
 *
 * The backtest panel starts from Bitunix VIP0 fees and real slippage
 * rather than zero, because a run with costs switched off describes a
 * strategy nobody can trade.
 */

import { useCallback, useEffect, useState } from 'react';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import { useAuthStore } from '@/lib/auth/store';
import { ForwardPanel } from '@/features/forward/ForwardPanel';
import { SaveSetupDialog } from '@/features/setups/SaveSetupDialog';
import { SetupPicker } from '@/features/setups/SetupPicker';
import { EquityChart } from './components/EquityChart';
import { CostsPanel } from './components/CostsPanel';
import { KpiStrip } from './components/KpiStrip';
import { StrategyEditor } from './components/StrategyEditor';
import { TradesTable } from './components/TradesTable';
import * as apiCalls from './lib/api';
import { duration, timestamp } from './lib/format';
import {
  DEFAULT_CONFIG,
  DEFAULT_EXITS,
  type BacktestConfig,
  type BacktestRun,
  type Strategy,
  type StrategyPayload,
} from './lib/types';
import styles from './TestPage.module.css';

const NEW_STRATEGY: StrategyPayload = {
  name: 'New strategy',
  long_entry: 'crossover(close, ema(close, 20))',
  short_entry: 'crossunder(close, ema(close, 20))',
  exits: { ...DEFAULT_EXITS },
  params: {},
};

type ResultTab = 'overview' | 'trades' | 'costs' | 'properties' | 'forward';

export function TestPage() {
  const user = useAuthStore((state) => state.user);
  const timezone = user?.timezone ?? 'UTC';

  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<StrategyPayload>(NEW_STRATEGY);
  const [draftValid, setDraftValid] = useState(true);

  const [symbol, setSymbol] = useState('BTCUSDT');
  const [interval, setIntervalValue] = useState('1h');
  const [config, setConfig] = useState<BacktestConfig>({ ...DEFAULT_CONFIG });

  const [run, setRun] = useState<BacktestRun | null>(null);
  const [tab, setTab] = useState<ResultTab>('overview');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savingSetup, setSavingSetup] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setStrategies(await apiCalls.listStrategies());
    } catch {
      // The list is a convenience; a failure here should not block editing.
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const select = (strategy: Strategy) => {
    setSelectedId(strategy.id);
    setDraft({
      name: strategy.name,
      long_entry: strategy.long_entry,
      short_entry: strategy.short_entry,
      exits: strategy.exits,
      params: strategy.params,
    });
    setRun(null);
    setError(null);
  };

  const save = async (): Promise<Strategy | null> => {
    setError(null);
    try {
      const saved = selectedId
        ? await apiCalls.updateStrategy(selectedId, draft)
        : await apiCalls.createStrategy(draft);
      setSelectedId(saved.id);
      await refresh();
      return saved;
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not save the strategy.');
      return null;
    }
  };

  const runBacktest = async () => {
    setBusy(true);
    setError(null);
    try {
      // Save first so the run is pinned to a stored version.
      const saved = await save();
      if (!saved) return;

      const result = await apiCalls.runBacktest(saved.id, {
        symbol,
        interval,
        config,
      });
      setRun(result);
      setTab('overview');
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The backtest could not be run.');
    } finally {
      setBusy(false);
    }
  };

  const setNumber = (key: keyof BacktestConfig) => (raw: string) => {
    const value = Number(raw);
    if (Number.isFinite(value)) setConfig((current) => ({ ...current, [key]: value }));
  };

  const selected = strategies.find((strategy) => strategy.id === selectedId) ?? null;

  // The forward test runs against a stored version, so it only needs a saved
  // strategy — not a backtest. The backtest tabs need a run.
  const tabs: [ResultTab, string][] = [
    ...((run
      ? [
          ['overview', 'Overview'],
          ['trades', 'List of trades'],
          ['costs', 'Costs & liquidation'],
          ['properties', 'Properties'],
        ]
      : []) as [ResultTab, string][]),
    ...((selected ? [['forward', 'Forward test']] : []) as [ResultTab, string][]),
  ];
  const activeTab: ResultTab = tabs.some(([key]) => key === tab)
    ? tab
    : (tabs[0]?.[0] ?? 'overview');

  /** Buy & hold rebased to the starting capital, for the equity overlay. */
  const benchmark = run
    ? (() => {
        const first = run.equity.value[0] ?? config.initial_capital;
        const growth = 1 + run.stats.buy_and_hold_percent / 100;
        const steps = run.equity.value.length;
        return run.equity.value.map((_, i) =>
          steps <= 1 ? first : first * (1 + (growth - 1) * (i / (steps - 1))),
        );
      })()
    : undefined;

  return (
    <div className={styles.page}>
      <aside className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          <span className={styles.sidebarTitle}>Strategies</span>
          <button
            type="button"
            className={styles.button}
            onClick={() => {
              setSelectedId(null);
              setDraft({ ...NEW_STRATEGY });
              setRun(null);
            }}
          >
            <Icon name="plus" size={14} />
            New
          </button>
        </div>

        <div className={styles.sidebarBody}>
          <div className={styles.strategyList}>
            {strategies.map((strategy) => (
              <button
                key={strategy.id}
                type="button"
                className={`${styles.strategyItem} ${
                  strategy.id === selectedId ? styles.active : ''
                }`}
                onClick={() => {
                  select(strategy);
                }}
              >
                <span>{strategy.name}</span>
                <span className={styles.strategyVersion}>{strategy.version.slice(0, 8)}</span>
              </button>
            ))}
          </div>

          <StrategyEditor value={draft} onChange={setDraft} onValidity={setDraftValid} />

          <div className={styles.label}>Backtest</div>
          <div className={styles.grid}>
            <label className={styles.field}>
              <span className={styles.label}>Symbol</span>
              <input
                className={styles.input}
                value={symbol}
                onChange={(event) => {
                  setSymbol(event.target.value.toUpperCase());
                }}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.label}>Timeframe</span>
              <select
                className={styles.select}
                value={interval}
                onChange={(event) => {
                  setIntervalValue(event.target.value);
                }}
              >
                {['1m', '5m', '15m', '1h', '4h', '1d'].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className={styles.field}>
              <span className={styles.label}>Capital</span>
              <input
                className={styles.input}
                type="number"
                value={config.initial_capital}
                onChange={(event) => {
                  setNumber('initial_capital')(event.target.value);
                }}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.label}>Margin %</span>
              <input
                className={styles.input}
                type="number"
                value={config.margin_percent}
                onChange={(event) => {
                  setNumber('margin_percent')(event.target.value);
                }}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.label}>Leverage</span>
              <input
                className={styles.input}
                type="number"
                min={1}
                max={200}
                value={config.leverage}
                onChange={(event) => {
                  setNumber('leverage')(event.target.value);
                }}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.label}>Margin mode</span>
              <select
                className={styles.select}
                value={config.margin_mode}
                onChange={(event) => {
                  setConfig((current) => ({
                    ...current,
                    margin_mode: event.target.value as 'isolated' | 'cross',
                  }));
                }}
              >
                <option value="isolated">Isolated</option>
                <option value="cross">Cross</option>
              </select>
            </label>
            <label className={styles.field}>
              <span className={styles.label}>Taker fee</span>
              <input
                className={styles.input}
                type="number"
                step={0.0001}
                value={config.taker_fee}
                onChange={(event) => {
                  setNumber('taker_fee')(event.target.value);
                }}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.label}>Slippage (bps)</span>
              <input
                className={styles.input}
                type="number"
                step={0.5}
                value={config.slippage_bps}
                onChange={(event) => {
                  setNumber('slippage_bps')(event.target.value);
                }}
              />
            </label>
          </div>

          <label className={styles.check}>
            <input
              type="checkbox"
              checked={config.apply_funding}
              onChange={(event) => {
                setConfig((current) => ({ ...current, apply_funding: event.target.checked }));
              }}
            />
            Charge funding every 8 hours
          </label>
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={config.use_magnifier}
              onChange={(event) => {
                setConfig((current) => ({ ...current, use_magnifier: event.target.checked }));
              }}
            />
            Use 1m bars to resolve intrabar exits
          </label>

          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}

          <div className={styles.actions}>
            <button
              type="button"
              className={styles.button}
              onClick={() => {
                void save();
              }}
              disabled={busy || !draftValid}
              title="Store a version without running it — enough to forward test"
            >
              Save
            </button>
            <button
              type="button"
              className={`${styles.button} ${styles.primary}`}
              onClick={() => {
                void runBacktest();
              }}
              disabled={busy || !draftValid}
            >
              {busy ? 'Running…' : 'Run backtest'}
            </button>
          </div>
        </div>
      </aside>

      <div className={styles.main}>
        <header className={styles.header}>
          <SetupPicker />

          {/* Only this middle strip scrolls, so the run's chips can never
              push the actions off the end of the header. */}
          <div className={styles.headerScroll}>
            <span className={styles.headerTitle}>{draft.name}</span>
            {run ? (
              <>
                <span className={styles.chip}>
                  <Icon name="lock" size={12} />
                  {run.strategy_version.slice(0, 12)}
                </span>
                <span className={styles.chip}>
                  {run.symbol} · {run.interval}
                </span>
                <span className={styles.chip}>
                  {timestamp(run.start_time, timezone)} – {timestamp(run.end_time, timezone)}
                </span>
                <span className={styles.chip}>
                  {config.leverage}× {config.margin_mode}
                </span>
              </>
            ) : null}
          </div>

          {run ? (
            <button
              type="button"
              className={styles.button}
              onClick={() => {
                setSavingSetup(true);
              }}
              title="Lock this version, market and sizing together"
            >
              <Icon name="lock" size={14} />
              Save as setup
            </button>
          ) : null}

          {run ? (
            <a className={styles.button} href={apiCalls.tradesCsvPath(run.id)} download>
              <Icon name="chevronDown" size={14} />
              Export CSV
            </a>
          ) : null}
        </header>

        {tabs.length > 0 ? (
          <>
            <nav className={styles.tabs}>
              {tabs.map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={`${styles.tab} ${activeTab === key ? styles.active : ''}`}
                  onClick={() => {
                    setTab(key);
                  }}
                >
                  {label}
                </button>
              ))}
            </nav>

            <div className={styles.content}>
              {run && activeTab === 'overview' ? (
                <>
                  <KpiStrip stats={run.stats} />
                  <div className={styles.split}>
                    <section
                      style={{
                        background: 'var(--surface)',
                        border: '1px solid var(--line)',
                        borderRadius: 'var(--radius-xl)',
                        padding: 'var(--space-4)',
                      }}
                    >
                      <div className={styles.label} style={{ marginBottom: 'var(--space-3)' }}>
                        Equity, with drawdown underneath
                      </div>
                      <EquityChart
                        time={run.equity.time}
                        equity={run.equity.value}
                        drawdown={run.equity.drawdown}
                        benchmark={benchmark}
                        height={360}
                      />
                    </section>
                    <div className={styles.sideStack}>
                      <CostsPanel stats={run.stats} trades={run.trades} />
                    </div>
                  </div>
                </>
              ) : null}

              {run && activeTab === 'trades' ? (
                <TradesTable trades={run.trades} timezone={timezone} />
              ) : null}

              {run && activeTab === 'costs' ? (
                <div className={styles.split}>
                  <CostsPanel stats={run.stats} trades={run.trades} />
                </div>
              ) : null}

              {run && activeTab === 'properties' ? (
                <section
                  style={{
                    background: 'var(--surface)',
                    border: '1px solid var(--line)',
                    borderRadius: 'var(--radius-xl)',
                    padding: 'var(--space-4)',
                  }}
                >
                  <dl className={styles.grid}>
                    <div className={styles.field}>
                      <span className={styles.label}>Strategy version</span>
                      <span className="num">{run.strategy_version.slice(0, 16)}</span>
                    </div>
                    <div className={styles.field}>
                      <span className={styles.label}>Bars</span>
                      <span className="num">{run.equity.time.length}</span>
                    </div>
                    <div className={styles.field}>
                      <span className={styles.label}>Run time</span>
                      <span className="num">{duration(run.duration_ms)}</span>
                    </div>
                    <div className={styles.field}>
                      <span className={styles.label}>Intrabar magnifier</span>
                      <span className="num">
                        {run.config['magnifier_used'] ? '1m bars' : 'stop assumed first'}
                      </span>
                    </div>
                    <div className={styles.field}>
                      <span className={styles.label}>Liquidations</span>
                      <span className={`num ${run.stats.liquidations > 0 ? 'down' : ''}`}>
                        {run.stats.liquidations}
                      </span>
                    </div>
                    <div className={styles.field}>
                      <span className={styles.label}>Ran at</span>
                      <span className="num">{timestamp(Date.parse(run.created_at), timezone)}</span>
                    </div>
                  </dl>
                </section>
              ) : null}

              {activeTab === 'forward' && selected ? (
                <ForwardPanel
                  strategyId={selected.id}
                  strategyVersion={selected.version}
                  symbol={symbol}
                  interval={interval}
                  config={config}
                  params={selected.params}
                />
              ) : null}
            </div>
          </>
        ) : (
          <div className={styles.placeholder}>
            Write a strategy on the left and run a backtest, or pick a saved strategy to forward
            test it.
            <br />
            Bars come from what the chart has already downloaded, so open the symbol and timeframe
            on the Chart menu first.
          </div>
        )}
      </div>

      {savingSetup && run && selectedId ? (
        <SaveSetupDialog
          strategyId={selectedId}
          strategyName={draft.name}
          strategyVersion={run.strategy_version}
          symbol={run.symbol}
          interval={run.interval}
          marginPercent={config.margin_percent}
          leverage={config.leverage}
          marginMode={config.margin_mode}
          makerFee={config.maker_fee}
          takerFee={config.taker_fee}
          sourceRunId={run.id}
          observedDrawdownPercent={run.stats.max_drawdown_percent}
          onClose={() => {
            setSavingSetup(false);
          }}
        />
      ) : null}
    </div>
  );
}
