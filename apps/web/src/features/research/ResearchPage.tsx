/**
 * The Research menu (SPEC §3.2).
 *
 * Four studies over one strategy and one market: how much leverage is
 * worth taking, how far trades go underwater, whether the result survives
 * being disturbed, and what relationships the data holds that nobody
 * looked for.
 *
 * Each runs on demand rather than on open. They are full backtests — a
 * leverage sweep is one per cell — and running four studies every time
 * someone glances at the menu would be a poor trade for the data centre
 * and the user both.
 */

import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import { SetupPicker } from '@/features/setups/SetupPicker';
import { useSelectedSetup } from '@/features/setups/lib/store';
import { DEFAULT_CONFIG, type BacktestConfig, type Strategy } from '@/features/test/lib/types';
import * as testApi from '@/features/test/lib/api';
import { DiscoverPanel } from './components/DiscoverPanel';
import { LeverageHeatmap } from './components/LeverageHeatmap';
import { MaeScatter } from './components/MaeScatter';
import * as researchApi from './lib/api';
import { watchJobs } from './lib/jobs';
import type { Cell, LeverageStudy, RobustnessStudy, TradeRiskStudy } from './lib/types';
import styles from './ResearchPage.module.css';

type Tab = 'leverage' | 'risk' | 'robustness' | 'discover';

const TABS: [Tab, string][] = [
  ['leverage', 'Leverage & costs'],
  ['risk', 'Trade risk'],
  ['robustness', 'Robustness'],
  ['discover', 'Relationships'],
];

const MARGINS = [5, 10, 20, 40];
const LEVERAGES = [1, 2, 5, 10, 25];

export function ResearchPage() {
  const setup = useSelectedSetup();
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [strategyId, setStrategyId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('leverage');

  const [symbol, setSymbol] = useState('BTCUSDT');
  const [interval, setIntervalValue] = useState('1h');
  const [budget, setBudget] = useState<string>('-25');
  const [config] = useState<BacktestConfig>({ ...DEFAULT_CONFIG });

  const [leverage, setLeverage] = useState<LeverageStudy | null>(null);
  const [risk, setRisk] = useState<TradeRiskStudy | null>(null);
  const [robustness, setRobustness] = useState<RobustnessStudy | null>(null);
  const [picked, setPicked] = useState<Cell | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The rail's Jobs ring reads from here, so it keeps counting while the
  // user is on another menu.
  useEffect(() => watchJobs(), []);

  useEffect(() => {
    void testApi
      .listStrategies()
      .then((rows) => {
        setStrategies(rows);
        setStrategyId((current) => current ?? rows[0]?.id ?? null);
      })
      .catch(() => {
        // The picker stays empty; the message below explains why.
      });
  }, []);

  // A Setup names the strategy and market it was validated under, so
  // selecting one should move the whole page rather than one field.
  useEffect(() => {
    if (!setup) return;
    setStrategyId(setup.strategy_id);
    setSymbol(setup.symbol);
    setIntervalValue(setup.interval);
  }, [setup]);

  const budgetValue = budget.trim() === '' ? null : Number(budget);

  const run = useCallback(
    async (which: Tab) => {
      if (!strategyId) return;
      setBusy(true);
      setError(null);
      const range = { symbol, interval, config };
      try {
        if (which === 'leverage') {
          const study = await researchApi.leverageStudy(strategyId, {
            ...range,
            margins: MARGINS,
            leverages: LEVERAGES,
            budget_percent:
              budgetValue !== null && Number.isFinite(budgetValue) && budgetValue < 0
                ? budgetValue
                : null,
          });
          setLeverage(study);
          setPicked(study.recommendation.cell);
        } else if (which === 'risk') {
          setRisk(await researchApi.tradeRiskStudy(strategyId, range));
        } else if (which === 'robustness') {
          const strategy = strategies.find((s) => s.id === strategyId);
          const params = strategy?.params ?? {};
          // Sweep each parameter around its current value so the surface
          // says whether the setting sits on a plateau or a spike.
          const grid = Object.fromEntries(
            Object.entries(params).map(([name, value]) => [
              name,
              [value * 0.5, value * 0.75, value, value * 1.25, value * 1.5].map(
                (v) => Math.round(v * 100) / 100,
              ),
            ]),
          );
          setRobustness(await researchApi.robustnessStudy(strategyId, { ...range, grid }));
        }
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : 'The study could not run.');
      } finally {
        setBusy(false);
      }
    },
    [strategyId, symbol, interval, config, budgetValue, strategies],
  );

  if (strategies.length === 0) {
    return (
      <div className={styles.page}>
        <header className={styles.header}>
          <SetupPicker />
        </header>
        <p className={styles.placeholder}>
          Research studies run against a saved strategy. Write one in the{' '}
          <Link to="/test">Test menu</Link> and save it first.
        </p>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <SetupPicker />

        <div className={styles.controls}>
          <select
            className={styles.select}
            value={strategyId ?? ''}
            onChange={(event) => {
              setStrategyId(event.target.value);
            }}
          >
            {strategies.map((strategy) => (
              <option key={strategy.id} value={strategy.id}>
                {strategy.name}
              </option>
            ))}
          </select>
          <input
            className={styles.input}
            value={symbol}
            onChange={(event) => {
              setSymbol(event.target.value.toUpperCase());
            }}
          />
          <select
            className={styles.select}
            value={interval}
            onChange={(event) => {
              setIntervalValue(event.target.value);
            }}
          >
            {['15m', '1h', '4h', '1d'].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
          <label className={styles.inlineField}>
            <span>Drawdown budget</span>
            <input
              className={styles.input}
              type="number"
              step={1}
              max={-1}
              value={budget}
              onChange={(event) => {
                setBudget(event.target.value);
              }}
            />
          </label>
        </div>
      </header>

      <nav className={styles.tabs}>
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`${styles.tab} ${tab === key ? styles.active : ''}`}
            onClick={() => {
              setTab(key);
            }}
          >
            {label}
          </button>
        ))}
      </nav>

      <div className={styles.body}>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}

        {tab === 'leverage' ? (
          <LeverageTab
            study={leverage}
            picked={picked}
            busy={busy}
            onPick={setPicked}
            onRun={() => void run('leverage')}
          />
        ) : null}

        {tab === 'risk' ? (
          <RiskTab study={risk} busy={busy} onRun={() => void run('risk')} />
        ) : null}

        {tab === 'robustness' ? (
          <RobustnessTab study={robustness} busy={busy} onRun={() => void run('robustness')} />
        ) : null}

        {tab === 'discover' ? <DiscoverPanel symbol={symbol} interval={interval} /> : null}
      </div>
    </div>
  );
}

function RunButton({ busy, onRun, label }: { busy: boolean; onRun: () => void; label: string }) {
  return (
    <button type="button" className={styles.run} disabled={busy} onClick={onRun}>
      {busy ? 'Running…' : label}
    </button>
  );
}

function LeverageTab({
  study,
  picked,
  busy,
  onPick,
  onRun,
}: {
  study: LeverageStudy | null;
  picked: Cell | null;
  busy: boolean;
  onPick: (cell: Cell) => void;
  onRun: () => void;
}) {
  return (
    <div className={styles.stack}>
      <div className={styles.runRow}>
        <p className={styles.hint}>
          One full backtest per cell — {MARGINS.length * LEVERAGES.length} runs.
        </p>
        <RunButton busy={busy} onRun={onRun} label="Run the sweep" />
      </div>

      {study ? (
        <>
          <section className={styles.panel}>
            <header className={styles.panelHeader}>
              <span className={styles.panelTitle}>Recommendation</span>
              <span className={styles.panelNote}>lowest leverage for the same exposure</span>
            </header>
            <div className={styles.panelBody}>
              <p className={styles.reason}>
                {study.recommendation.cell ? (
                  <>
                    <Icon name="check" size={14} /> {study.recommendation.reason}
                  </>
                ) : (
                  <>
                    <Icon name="warning" size={14} /> {study.recommendation.reason}
                  </>
                )}
              </p>
            </div>
          </section>

          <section className={styles.panel}>
            <header className={styles.panelHeader}>
              <span className={styles.panelTitle}>Margin × leverage</span>
              <span className={styles.panelNote}>
                {study.bars.toLocaleString()} bars · {study.strategy_version.slice(0, 12)}
              </span>
            </header>
            <div className={styles.panelBody}>
              <LeverageHeatmap
                cells={study.cells}
                budgetPercent={study.budget_percent}
                selected={picked}
                onSelect={onPick}
              />
            </div>
          </section>

          <section className={styles.panel}>
            <header className={styles.panelHeader}>
              <span className={styles.panelTitle}>Isolated vs cross</span>
              <span className={styles.panelNote}>at the recommended sizing</span>
            </header>
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Mode</th>
                    <th>Exposure</th>
                    <th>Liquidation distance</th>
                    <th>Net</th>
                    <th>Max DD</th>
                    <th>Worst trade</th>
                    <th>Liquidations</th>
                    <th>Costs ÷ gross</th>
                    <th>Risk of ruin</th>
                  </tr>
                </thead>
                <tbody>
                  {study.margin_modes.map((row) => (
                    <tr key={row.margin_mode}>
                      <td>{row.margin_mode}</td>
                      <td className="num">{row.exposure.toFixed(2)}×</td>
                      <td className="num">{row.liquidation_distance_percent.toFixed(2)}%</td>
                      <td className={`num ${row.net_percent >= 0 ? 'up' : 'down'}`}>
                        {row.net_percent >= 0 ? '+' : ''}
                        {row.net_percent.toFixed(2)}%
                      </td>
                      <td className="num down">{row.max_drawdown_percent.toFixed(2)}%</td>
                      <td className="num down">{row.worst_trade_percent.toFixed(2)}%</td>
                      <td className={`num ${row.liquidations > 0 ? 'down' : ''}`}>
                        {row.liquidations}
                      </td>
                      <td className="num">
                        {row.costs_over_gross === null
                          ? '—'
                          : `${(row.costs_over_gross * 100).toFixed(0)}%`}
                      </td>
                      <td className={`num ${row.risk_of_ruin_percent > 5 ? 'down' : ''}`}>
                        {row.risk_of_ruin_percent.toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function RiskTab({
  study,
  busy,
  onRun,
}: {
  study: TradeRiskStudy | null;
  busy: boolean;
  onRun: () => void;
}) {
  return (
    <div className={styles.stack}>
      <div className={styles.runRow}>
        <p className={styles.hint}>
          How far each trade went underwater before it closed, against the margin committed.
        </p>
        <RunButton busy={busy} onRun={onRun} label="Run trade risk" />
      </div>

      {study ? (
        <>
          <div className={styles.kpis}>
            <Kpi
              label="Winners that were red first"
              value={`${study.kpis.winners_that_were_red} of ${study.kpis.winners}`}
              note="trades you had to hold through a loss"
            />
            <Kpi
              label="Median dip"
              value={`${study.kpis.median_dip_percent.toFixed(1)}%`}
              note="of margin, on winning trades"
            />
            <Kpi
              label="95th percentile dip"
              value={`${study.kpis.p95_dip_percent.toFixed(1)}%`}
              note="one winner in twenty went at least this deep"
            />
            <Kpi
              label="Survives up to"
              value={`${study.kpis.survives_up_to_leverage.toFixed(1)}×`}
              note={`the deepest dip was ${study.kpis.deepest_dip_percent.toFixed(1)}%`}
            />
            <Kpi
              label="Worst closed trade"
              value={`${study.kpis.worst_closed_trade_percent.toFixed(1)}%`}
              note="of margin"
            />
            <Kpi
              label="Funding"
              value={study.kpis.total_funding.toFixed(2)}
              note={`${study.kpis.funding_events} trades paid it`}
            />
          </div>

          <section className={styles.panel}>
            <header className={styles.panelHeader}>
              <span className={styles.panelTitle}>Worst dip against final result</span>
              <span className={styles.panelNote}>vertical lines are where leverage liquidates</span>
            </header>
            <div className={styles.panelBody}>
              <MaeScatter points={study.points} />
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function RobustnessTab({
  study,
  busy,
  onRun,
}: {
  study: RobustnessStudy | null;
  busy: boolean;
  onRun: () => void;
}) {
  return (
    <div className={styles.stack}>
      <div className={styles.runRow}>
        <p className={styles.hint}>
          Disturb the run and see what is left: worse costs, a different order of trades, the best
          trades taken away.
        </p>
        <RunButton busy={busy} onRun={onRun} label="Run robustness" />
      </div>

      {study ? (
        <>
          <section className={styles.panel}>
            <header className={styles.panelHeader}>
              <span className={styles.panelTitle}>Stress cases</span>
              <span className={styles.panelNote}>against the run as configured</span>
            </header>
            <div className={styles.tableScroll}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Net</th>
                    <th>Change</th>
                    <th>Max DD</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {study.stress.map((row) => (
                    <tr key={row.name}>
                      <td>
                        <span className={styles.caseName}>{row.name}</span>
                        <span className={styles.caseNote}>{row.description}</span>
                      </td>
                      <td className={`num ${row.net_percent >= 0 ? 'up' : 'down'}`}>
                        {row.net_percent >= 0 ? '+' : ''}
                        {row.net_percent.toFixed(2)}%
                      </td>
                      <td className={`num ${row.delta_percent >= 0 ? 'up' : 'down'}`}>
                        {row.delta_percent >= 0 ? '+' : ''}
                        {row.delta_percent.toFixed(2)} pt
                      </td>
                      <td className="num down">{row.max_drawdown_percent.toFixed(2)}%</td>
                      <td>
                        {row.adverse ? (
                          <span className={row.survived ? styles.pass : styles.fail}>
                            {row.survived ? 'survived' : 'failed'}
                          </span>
                        ) : (
                          <span className={styles.neutral} title="Cheaper than the default tier">
                            what-if
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div className={styles.kpis}>
            <Kpi
              label="Reshuffled years · median"
              value={`${study.reshuffled.median_percent.toFixed(1)}%`}
              note={`${study.trades_per_year} trades a year`}
            />
            <Kpi
              label="5th percentile"
              value={`${study.reshuffled.p5_percent.toFixed(1)}%`}
              note="one year in twenty was at least this bad"
            />
            <Kpi
              label="Halved the account"
              value={`${study.reshuffled.ruin_rate.toFixed(1)}%`}
              note="of reshuffled years"
            />
            <Kpi
              label="Daily VaR 95%"
              value={`${study.risk.var_95_percent.toFixed(2)}%`}
              note="where the worst 5% begins"
            />
            <Kpi
              label="CVaR 95%"
              value={`${study.risk.cvar_95_percent.toFixed(2)}%`}
              note="the average of that tail"
            />
            <Kpi
              label="Half Kelly"
              value={`${(study.risk.half_kelly_fraction * 100).toFixed(1)}%`}
              note={`full Kelly ${(study.risk.kelly_fraction * 100).toFixed(1)}% — too aggressive to trade`}
            />
          </div>

          {study.surface.best ? (
            <section className={styles.panel}>
              <header className={styles.panelHeader}>
                <span className={styles.panelTitle}>Parameter surface</span>
                <span className={styles.panelNote}>
                  {study.surface.plateau ? 'plateau' : 'lone peak'}
                </span>
              </header>
              <div className={styles.panelBody}>
                <p className={styles.reason}>
                  {study.surface.plateau ? (
                    <>
                      <Icon name="check" size={14} /> The best setting is supported by its
                      neighbours, which average{' '}
                      {study.surface.neighbourhood_mean_percent.toFixed(1)}% against its{' '}
                      {study.surface.best.net_percent.toFixed(1)}%. That is what a real effect looks
                      like.
                    </>
                  ) : (
                    <>
                      <Icon name="warning" size={14} /> The best setting stands alone — its
                      neighbours average {study.surface.neighbourhood_mean_percent.toFixed(1)}%
                      against its {study.surface.best.net_percent.toFixed(1)}%. A peak nothing
                      around it supports is usually a fit to this history.
                    </>
                  )}
                </p>
              </div>
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function Kpi({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className={styles.kpi}>
      <span className={styles.kpiLabel}>{label}</span>
      <span className={styles.kpiValue}>{value}</span>
      <span className={styles.kpiNote}>{note}</span>
    </div>
  );
}
