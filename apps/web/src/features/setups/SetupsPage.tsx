/**
 * The Setups overview (SPEC §3.2).
 *
 * The pipeline table answers "how far has each setup got"; the conflict
 * panel answers the question no single setup can — what happens when they
 * run together. Two setups on one symbol in one-way mode close each
 * other's positions, and the exchange will not refuse it, so the warning
 * has to come from here.
 */

import { useCallback, useEffect, useState } from 'react';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import { StageChips } from './components/StageChips';
import * as setupsApi from './lib/api';
import { useSetupsStore } from './lib/store';
import {
  PIPELINE_STAGES,
  STAGE_NAMES,
  stageStatus,
  usedIn,
  type ConflictWarning,
  type Setup,
  type SetupsOverview,
  type Stage,
} from './lib/types';
import styles from './SetupsPage.module.css';

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

function liveCount(setups: Setup[]): { bot: number; paper: number; alerts: number } {
  return {
    bot: setups.filter((setup) => setup.use_in_bot).length,
    paper: setups.filter((setup) => setup.use_in_paper).length,
    alerts: setups.filter((setup) => setup.use_in_alerts).length,
  };
}

/** Exposure of the setups that actually place orders. */
function liveExposure(setups: Setup[]): number {
  return setups
    .filter((setup) => setup.use_in_bot || setup.use_in_paper)
    .reduce((total, setup) => total + setup.exposure, 0);
}

function marketSpread(setups: Setup[]): string {
  const bySymbol = new Map<string, number>();
  for (const setup of setups) bySymbol.set(setup.symbol, (bySymbol.get(setup.symbol) ?? 0) + 1);
  return (
    [...bySymbol.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([symbol, count]) => `${symbol.replace('USDT', '')} ${count}`)
      .join(' · ') || '—'
  );
}

/** The furthest stage a setup has passed, for the "reached" column. */
function reached(setup: Setup): Stage | null {
  let furthest: Stage | null = null;
  for (const stage of PIPELINE_STAGES) {
    if (stageStatus(setup, stage) === 'passed') furthest = stage;
  }
  return furthest;
}

export function SetupsPage() {
  const [overview, setOverview] = useState<SetupsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const reload = useSetupsStore((state) => state.load);

  const refresh = useCallback(async () => {
    try {
      setOverview(await setupsApi.setupsOverview());
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The setups could not be loaded.');
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const archive = async (setup: Setup) => {
    setBusyId(setup.id);
    try {
      await setupsApi.archiveSetup(setup.id);
      await refresh();
      await reload();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The setup could not be archived.');
    } finally {
      setBusyId(null);
    }
  };

  const setups = overview?.setups ?? [];
  const live = liveCount(setups);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <span className={styles.chip}>
          {plural(setups.length, 'setup')} ·{' '}
          {plural(new Set(setups.map((setup) => setup.symbol)).size, 'market')}
        </span>
        <span className={styles.spacer} />
        <span className={styles.pipeline}>
          {PIPELINE_STAGES.map((stage, index) => (
            <span key={stage}>
              {index > 0 ? <span className={styles.arrow}>→</span> : null}
              {STAGE_NAMES[stage]}
            </span>
          ))}
        </span>
      </header>

      <div className={styles.body}>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}

        <div className={styles.kpis}>
          <div className={styles.kpi}>
            <span className={styles.kpiLabel}>Running now</span>
            <span className={styles.kpiValue}>{live.bot + live.paper + live.alerts}</span>
            <span className={styles.kpiNote}>
              {live.bot} bot · {live.paper} paper · {live.alerts} alerts
            </span>
          </div>
          <div className={styles.kpi}>
            <span className={styles.kpiLabel}>Live exposure</span>
            <span className={styles.kpiValue}>{(liveExposure(setups) / 100).toFixed(2)}×</span>
            <span className={styles.kpiNote}>equity, bot and paper only</span>
          </div>
          <div className={styles.kpi}>
            <span className={styles.kpiLabel}>Total exposure</span>
            <span className={styles.kpiValue}>
              {((overview?.total_exposure ?? 0) / 100).toFixed(2)}×
            </span>
            <span className={styles.kpiNote}>every setup, whether live or not</span>
          </div>
          <div className={styles.kpi}>
            <span className={styles.kpiLabel}>Markets</span>
            <span className={styles.kpiValue}>{marketSpread(setups)}</span>
            <span className={styles.kpiNote}>setups per symbol</span>
          </div>
        </div>

        <section className={styles.panel}>
          <header className={styles.panelHeader}>
            <span className={styles.panelTitle}>Pipeline</span>
            <span className={styles.panelNote}>research → backtest → forward → paper → bot</span>
          </header>

          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Setup</th>
                  <th>Market</th>
                  <th>Position</th>
                  <th>Exposure</th>
                  <th>Budget</th>
                  <th>Stages</th>
                  <th>Reached</th>
                  <th>Used in</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {setups.map((setup) => {
                  const furthest = reached(setup);
                  return (
                    <tr key={setup.id}>
                      <td>
                        <span className={styles.name}>
                          <span className={styles.swatch} style={{ background: setup.color }} />
                          {setup.name}
                        </span>
                        <span className={styles.sub}>
                          {setup.strategy_version.slice(0, 12)} · locked
                        </span>
                      </td>
                      <td className="num">
                        {setup.symbol} · {setup.interval}
                      </td>
                      <td className="num">
                        {setup.margin_percent}% × {setup.leverage}×
                        <span className={styles.sub}>{setup.margin_mode}</span>
                      </td>
                      <td className="num">{setup.exposure.toFixed(0)}%</td>
                      <td
                        className={`num ${setup.max_drawdown_budget_percent === null ? '' : 'down'}`}
                      >
                        {setup.max_drawdown_budget_percent === null
                          ? '—'
                          : `${setup.max_drawdown_budget_percent.toFixed(1)}%`}
                      </td>
                      <td>
                        <StageChips setup={setup} />
                      </td>
                      <td className={styles.subCell}>
                        {furthest ? STAGE_NAMES[furthest] : 'not started'}
                      </td>
                      <td className={styles.subCell}>{usedIn(setup).join(', ') || 'nowhere'}</td>
                      <td>
                        <button
                          type="button"
                          className={styles.archive}
                          disabled={busyId === setup.id}
                          title="Archive: the setup stays as the provenance of past runs"
                          onClick={() => {
                            void archive(setup);
                          }}
                        >
                          <Icon name="trash" size={14} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {setups.length === 0 ? (
            <p className={styles.empty}>
              No setups yet. Run a backtest in the Test menu and save the result as one — that is
              what locks a strategy version to the market and sizing it was validated under.
            </p>
          ) : null}
        </section>

        <section className={styles.panel}>
          <header className={styles.panelHeader}>
            <span className={styles.panelTitle}>Running several setups together</span>
            <span className={styles.panelNote}>checked automatically</span>
          </header>

          {overview && overview.conflicts.length > 0 ? (
            overview.conflicts.map((conflict) => (
              <Warning key={conflict.kind + conflict.setup_ids.join()} conflict={conflict} />
            ))
          ) : (
            <p className={styles.clear}>
              <Icon name="check" size={14} />
              Nothing conflicts. Two setups trading one symbol on the same account, or live exposure
              over 1×, would show up here.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

function Warning({ conflict }: { conflict: ConflictWarning }) {
  // Exposure and overlapping symbols can cost real money; a stacked
  // drawdown budget is a planning note.
  const severe = conflict.kind === 'same_symbol' || conflict.kind === 'exposure';
  return (
    <p className={`${styles.warning} ${severe ? styles.warningSevere : ''}`}>
      <Icon name={severe ? 'warning' : 'clock'} size={14} />
      <span>{conflict.message}</span>
      <span className={styles.subCell}>{plural(conflict.setup_ids.length, 'setup')}</span>
    </p>
  );
}
