/**
 * Paper trading and the promotion checklist (SPEC §3.3).
 *
 * The checklist is the point of the panel. "It works" has to mean
 * something specific before a Setup may place real orders, so each check
 * is shown with the number it was judged on — a checklist that says
 * "failed" without saying what the figure was cannot be acted on.
 */

import { useCallback, useEffect, useState } from 'react';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import * as alertsApi from '../lib/api';
import type { PaperSession } from '../lib/types';
import styles from './alerts.module.css';

export function PaperPanel() {
  const [sessions, setSessions] = useState<PaperSession[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setSessions(await alertsApi.listPaperSessions());
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not load paper sessions.');
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const promote = async (session: PaperSession) => {
    try {
      await alertsApi.promotePaper(session.id);
      await refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not promote that session.');
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
    return (
      <p className={styles.placeholder}>
        No paper sessions. Paper trading runs a Setup&rsquo;s own rules against live prices with no
        money, and is what unlocks the bot stage.
      </p>
    );
  }

  return (
    <div className={styles.list}>
      {sessions.map((session) => (
        <article key={session.id} className={styles.card}>
          <header className={styles.cardHeader}>
            <span className={styles.cardTitle}>
              {session.state === 'promoted' ? 'Promoted' : 'Paper session'}
            </span>
            <span className={styles.badge}>{session.state}</span>
            <span className={styles.meta}>
              since {new Date(session.started_at).toLocaleDateString()}
            </span>
            <span className={styles.spacer} />
            {session.promoted_by_override ? (
              <span className={styles.warnBadge} title="A check was failing when this was promoted">
                promoted on an override
              </span>
            ) : null}
          </header>

          <dl className={styles.kpis}>
            <Kpi
              label="Net"
              value={`${session.net_percent >= 0 ? '+' : ''}${session.net_percent.toFixed(2)}%`}
              note={
                session.expected.low_percent !== null && session.expected.high_percent !== null
                  ? `expected ${session.expected.low_percent.toFixed(1)}% to ${session.expected.high_percent.toFixed(1)}%`
                  : 'no expected range recorded'
              }
            />
            <Kpi
              label="Max drawdown"
              value={`${session.max_drawdown_percent.toFixed(2)}%`}
              note={
                session.expected.drawdown_limit_percent !== null
                  ? `limit ${session.expected.drawdown_limit_percent.toFixed(1)}%`
                  : 'no limit set'
              }
            />
            <Kpi label="Fills" value={String(session.execution.fills)} note="live executions" />
            <Kpi
              label="Drift"
              value={`${session.execution.drift_percent.toFixed(4)}%`}
              note={`${session.execution.mean_slippage_bps.toFixed(2)} bps against the assumption`}
            />
            <Kpi
              label="Latency"
              value={`${Math.round(session.execution.mean_latency_ms)} ms`}
              note="signal to fill"
            />
            <Kpi
              label="Missed signals"
              value={String(session.missed_signals)}
              note="no fill was recorded"
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
                Promoted {session.promoted_at ? new Date(session.promoted_at).toLocaleString() : ''}
              </span>
            ) : (
              <>
                <button
                  type="button"
                  className={`${styles.button} ${styles.primary}`}
                  disabled={!session.promotion.ready}
                  title={
                    session.promotion.ready
                      ? 'Unlock the bot stage for this setup'
                      : session.promotion.blocking.join('; ')
                  }
                  onClick={() => {
                    void promote(session);
                  }}
                >
                  Promote to bot
                </button>
                {!session.promotion.ready ? (
                  <span className={styles.meta}>
                    Still needed: {session.promotion.blocking.join(', ').toLowerCase()}
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
