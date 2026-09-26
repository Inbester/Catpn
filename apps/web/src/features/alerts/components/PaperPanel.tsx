/**
 * Paper trading and the promotion checklist (SPEC §3.3).
 *
 * The checklist is the point of the panel. "It works" has to mean
 * something specific before a Setup may place real orders, so each check
 * is shown with the number it was judged on — a checklist that says
 * "failed" without saying what the figure was cannot be acted on.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import * as alertsApi from '../lib/api';
import type { PaperSession } from '../lib/types';
import styles from './alerts.module.css';

export function PaperPanel() {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<PaperSession[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setSessions(await alertsApi.listPaperSessions());
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('alertsPage.paper.loadFailed'));
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const promote = async (session: PaperSession) => {
    try {
      await alertsApi.promotePaper(session.id);
      await refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('alertsPage.paper.promoteFailed'));
    }
  };

  if (error) {
    return (
      <p className={styles.error} role="alert">
        {error}
      </p>
    );
  }

  if (sessions.length === 0) {
    return <p className={styles.placeholder}>{t('alertsPage.paper.empty')}</p>;
  }

  return (
    <div className={styles.list}>
      {sessions.map((session) => (
        <article key={session.id} className={styles.card}>
          <header className={styles.cardHeader}>
            <span className={styles.cardTitle}>
              {session.state === 'promoted'
                ? t('alertsPage.paper.promoted')
                : t('alertsPage.paper.session')}
            </span>
            <span className={styles.badge}>{session.state}</span>
            <span className={styles.meta}>
              {t('alertsPage.paper.since', {
                date: new Date(session.started_at).toLocaleDateString(),
              })}
            </span>
            <span className={styles.spacer} />
            {session.promoted_by_override ? (
              <span className={styles.warnBadge} title={t('alertsPage.paper.overrideTitle')}>
                {t('alertsPage.paper.overrideBadge')}
              </span>
            ) : null}
          </header>

          <dl className={styles.kpis}>
            <Kpi
              label={t('alertsPage.paper.net')}
              value={`${session.net_percent >= 0 ? '+' : ''}${session.net_percent.toFixed(2)}%`}
              note={
                session.expected.low_percent !== null && session.expected.high_percent !== null
                  ? t('alertsPage.paper.expectedRange', {
                      low: session.expected.low_percent.toFixed(1),
                      high: session.expected.high_percent.toFixed(1),
                    })
                  : t('alertsPage.paper.noExpected')
              }
            />
            <Kpi
              label={t('alertsPage.paper.maxDrawdown')}
              value={`${session.max_drawdown_percent.toFixed(2)}%`}
              note={
                session.expected.drawdown_limit_percent !== null
                  ? t('alertsPage.paper.limit', {
                      percent: session.expected.drawdown_limit_percent.toFixed(1),
                    })
                  : t('alertsPage.paper.noLimit')
              }
            />
            <Kpi
              label={t('alertsPage.paper.fills')}
              value={String(session.execution.fills)}
              note={t('alertsPage.paper.fillsNote')}
            />
            <Kpi
              label={t('alertsPage.paper.drift')}
              value={`${session.execution.drift_percent.toFixed(4)}%`}
              note={t('alertsPage.paper.driftNote', {
                bps: session.execution.mean_slippage_bps.toFixed(2),
              })}
            />
            <Kpi
              label={t('alertsPage.paper.latency')}
              value={`${Math.round(session.execution.mean_latency_ms)} ms`}
              note={t('alertsPage.paper.latencyNote')}
            />
            <Kpi
              label={t('alertsPage.paper.missed')}
              value={String(session.missed_signals)}
              note={t('alertsPage.paper.missedNote')}
            />
          </dl>

          <div className={styles.checklist}>
            {session.promotion.checks.map((check) => (
              <div key={check.key} className={styles.checkRow}>
                <Icon
                  name={check.passed ? 'check' : 'close'}
                  size={13}
                  className={check.passed ? styles.pass : styles.fail}
                />
                <span className={styles.checkLabel}>{check.label}</span>
                <span className={styles.checkDetail}>{check.detail}</span>
              </div>
            ))}
          </div>

          <footer className={styles.cardFooter}>
            {session.state === 'promoted' ? (
              <span className={styles.meta}>
                {t('alertsPage.paper.promotedAt', {
                  when: session.promoted_at ? new Date(session.promoted_at).toLocaleString() : '',
                })}
              </span>
            ) : (
              <>
                <button
                  type="button"
                  className={`${styles.button} ${styles.primary}`}
                  disabled={!session.promotion.ready}
                  title={
                    session.promotion.ready
                      ? t('alertsPage.paper.promoteReady')
                      : session.promotion.blocking.join('; ')
                  }
                  onClick={() => {
                    void promote(session);
                  }}
                >
                  {t('alertsPage.paper.promote')}
                </button>
                {!session.promotion.ready ? (
                  <span className={styles.meta}>
                    {t('alertsPage.paper.stillNeeded', {
                      blocking: session.promotion.blocking.join(', ').toLowerCase(),
                    })}
                  </span>
                ) : null}
              </>
            )}
          </footer>
        </article>
      ))}
    </div>
  );
}

function Kpi({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className={styles.kpi}>
      <dt>{label}</dt>
      <dd>
        {value}
        <span className={styles.kpiNote}>{note}</span>
      </dd>
    </div>
  );
}
