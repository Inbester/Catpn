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
import { useTranslation } from 'react-i18next';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import { StageChips } from './components/StageChips';
import * as setupsApi from './lib/api';
import { useSetupsStore } from './lib/store';
import {
  PIPELINE_STAGES,
  stageStatus,
  usedIn,
  type ConflictWarning,
  type Setup,
  type SetupsOverview,
  type Stage,
} from './lib/types';
import styles from './SetupsPage.module.css';

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
  const { t } = useTranslation();
  const [overview, setOverview] = useState<SetupsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const reload = useSetupsStore((state) => state.load);

  const refresh = useCallback(async () => {
    try {
      setOverview(await setupsApi.setupsOverview());
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('setups.loadFailed'));
    }
  }, [t]);

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
      setError(caught instanceof ApiError ? caught.message : t('setups.archiveFailed'));
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
          {t('setups.count', { count: setups.length })} ·{' '}
          {t('setups.marketCount', {
            count: new Set(setups.map((setup) => setup.symbol)).size,
          })}
        </span>
        <span className={styles.spacer} />
        <span className={styles.pipeline}>
          {PIPELINE_STAGES.map((stage, index) => (
            <span key={stage}>
              {index > 0 ? <span className={styles.arrow}>→</span> : null}
              {t(`setups.stage.${stage}`)}
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
            <span className={styles.kpiLabel}>{t('setups.runningNow')}</span>
            <span className={styles.kpiValue}>{live.bot + live.paper + live.alerts}</span>
          </div>
          <div className={styles.kpi}>
            <span className={styles.kpiLabel}>{t('setups.liveExposure')}</span>
            <span className={styles.kpiValue}>{(liveExposure(setups) / 100).toFixed(2)}×</span>
            <span className={styles.kpiNote}>{t('setups.liveExposureNote')}</span>
          </div>
          <div className={styles.kpi}>
            <span className={styles.kpiLabel}>{t('setups.totalExposure')}</span>
            <span className={styles.kpiValue}>
              {((overview?.total_exposure ?? 0) / 100).toFixed(2)}×
            </span>
            <span className={styles.kpiNote}>{t('setups.totalExposureNote')}</span>
          </div>
          <div className={styles.kpi}>
            <span className={styles.kpiLabel}>{t('setups.markets')}</span>
            <span className={styles.kpiValue}>{marketSpread(setups)}</span>
            <span className={styles.kpiNote}>{t('setups.marketsNote')}</span>
          </div>
        </div>

        <section className={styles.panel}>
          <header className={styles.panelHeader}>
            <span className={styles.panelTitle}>{t('setups.pipeline')}</span>
            <span className={styles.panelNote}>{t('setups.pipelineNote')}</span>
          </header>

          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>{t('setups.colSetup')}</th>
                  <th>{t('setups.colMarket')}</th>
                  <th>{t('setups.colPosition')}</th>
                  <th>{t('setups.colExposure')}</th>
                  <th>{t('setups.colBudget')}</th>
                  <th>{t('setups.colStages')}</th>
                  <th>{t('setups.colReached')}</th>
                  <th>{t('setups.colUsedIn')}</th>
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
                          {setup.strategy_version.slice(0, 12)} · {t('setups.locked')}
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
                        {furthest ? t(`setups.stage.${furthest}`) : t('setups.notStarted')}
                      </td>
                      <td className={styles.subCell}>
                        {usedIn(setup)
                          .map((use) => t(`setups.use.${use}`))
                          .join(', ') || t('setups.nowhere')}
                      </td>
                      <td>
                        <button
                          type="button"
                          className={styles.archive}
                          disabled={busyId === setup.id}
                          title={t('setups.archiveTitle')}
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

          {setups.length === 0 ? <p className={styles.empty}>{t('setups.empty')}</p> : null}
        </section>

        <section className={styles.panel}>
          <header className={styles.panelHeader}>
            <span className={styles.panelTitle}>{t('setups.conflictsTitle')}</span>
            <span className={styles.panelNote}>{t('setups.conflictsNote')}</span>
          </header>

          {overview && overview.conflicts.length > 0 ? (
            overview.conflicts.map((conflict) => (
              <Warning key={conflict.kind + conflict.setup_ids.join()} conflict={conflict} />
            ))
          ) : (
            <p className={styles.clear}>
              <Icon name="check" size={14} />
              {t('setups.noConflicts')}
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
      <span className={styles.subCell}>{conflict.setup_ids.length}</span>
    </p>
  );
}
