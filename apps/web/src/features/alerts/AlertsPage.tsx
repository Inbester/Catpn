/**
 * The Alerts menu (SPEC §3.4).
 *
 * Two halves: the alerts themselves, and what they actually did. The
 * second half is the one that matters. An alert the user believes is
 * watching over them, which has been silently failing to deliver, is
 * worse than no alert at all — so every firing appears here with its
 * per-destination outcome, including the ones a repeat rule suppressed
 * and the ones a burst folded together.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import { useSetupsStore } from '@/features/setups/lib/store';
import { useActiveAlerts } from './lib/activeAlerts';
import * as alertsApi from './lib/api';
import { AlertForm } from './components/AlertForm';
import type { Alert, AlertEvent } from './lib/types';
import { PaperPanel } from './components/PaperPanel';
import styles from './AlertsPage.module.css';

type Tab = 'alerts' | 'activity' | 'paper';

export function AlertsPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('alerts');
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [editing, setEditing] = useState<Alert | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setups = useSetupsStore((state) => state.setups);
  const loadSetups = useSetupsStore((state) => state.load);

  const refresh = useCallback(async () => {
    try {
      const [rows, feed] = await Promise.all([
        alertsApi.listAlerts(),
        alertsApi.listEvents().catch(() => []),
      ]);
      setAlerts(rows);
      setEvents(feed);
      setError(null);
      // The rail's bell polls slowly, because an alert's state only
      // changes when someone changes it. This is that someone, so it is
      // refreshed here rather than leaving the badge stale for half a
      // minute after a create or delete.
      void useActiveAlerts
        .getState()
        .load()
        .catch(() => undefined);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('alertsPage.loadFailed'));
    }
  }, [t]);

  useEffect(() => {
    void refresh();
    void loadSetups().catch(() => {
      // The setup picker in the form falls back to none.
    });
  }, [refresh, loadSetups]);

  // The activity feed is the only view that changes without the user
  // doing anything, so it is the only one that polls.
  useEffect(() => {
    if (tab !== 'activity') return;
    const timer = setInterval(() => {
      void alertsApi
        .listEvents()
        .then(setEvents)
        .catch(() => undefined);
    }, 5_000);
    return () => {
      clearInterval(timer);
    };
  }, [tab]);

  const remove = async (alert: Alert) => {
    try {
      await alertsApi.deleteAlert(alert.id);
      await refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('alertsPage.deleteFailed'));
    }
  };

  const test = async (alert: Alert) => {
    try {
      await alertsApi.testSend(alert.id);
      setTab('activity');
      await refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : t('alertsPage.testFailed'));
    }
  };

  return (
    <div className={styles.page}>
      <nav className={styles.tabs}>
        {(
          [
            ['alerts', `${t('alertsPage.tabAlerts')}${alerts.length ? ` · ${alerts.length}` : ''}`],
            ['activity', t('alertsPage.tabActivity')],
            ['paper', t('alertsPage.tabPaper')],
          ] as [Tab, string][]
        ).map(([key, label]) => (
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

        <span className={styles.spacer} />

        {tab === 'alerts' ? (
          <button
            type="button"
            className={styles.primary}
            onClick={() => {
              setCreating(true);
              setEditing(null);
            }}
          >
            <Icon name="plus" size={14} />
            {t('alertsPage.newAlert')}
          </button>
        ) : null}
      </nav>

      <div className={styles.body}>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}

        {tab === 'alerts' ? (
          alerts.length === 0 ? (
            <p className={styles.placeholder}>{t('alertsPage.empty')}</p>
          ) : (
            <div className={styles.list}>
              {alerts.map((alert) => (
                <article key={alert.id} className={styles.card}>
                  <header className={styles.cardHeader}>
                    <span className={styles.cardTitle}>{alert.name}</span>
                    <span className={styles.badge}>{t(`alertsPage.source.${alert.source}`)}</span>
                    <span className={styles.meta}>
                      {alert.symbol} · {alert.interval}
                    </span>
                    <span className={styles.spacer} />
                    {alert.enabled ? (
                      <span className={styles.on}>{t('alertsPage.on')}</span>
                    ) : (
                      <span className={styles.off}>{t('alertsPage.off')}</span>
                    )}
                  </header>

                  <dl className={styles.cardBody}>
                    <div>
                      <dt>{t('alertsPage.fires')}</dt>
                      <dd>
                        {t(`alertsPage.repeat.${alert.repeat_mode}`)} ·{' '}
                        {alert.trigger_mode === 'bar_close'
                          ? t('alertsPage.onBarClose')
                          : t('alertsPage.everyTick')}
                      </dd>
                    </div>
                    <div>
                      <dt>{t('alertsPage.sendsTo')}</dt>
                      <dd>
                        {alert.destinations.length === 0
                          ? t('alertsPage.nowhereYet')
                          : alert.destinations.map((d) => d.kind).join(', ')}
                      </dd>
                    </div>
                    <div>
                      <dt>{t('alertsPage.quietHours')}</dt>
                      <dd>
                        {alert.quiet_from_hour === null
                          ? t('alertsPage.quietNone')
                          : t('alertsPage.quietWindow', {
                              from: alert.quiet_from_hour,
                              to: alert.quiet_to_hour,
                            })}
                      </dd>
                    </div>
                    <div>
                      <dt>{t('alertsPage.fired')}</dt>
                      <dd>
                        {t('alertsPage.firedCount', { count: alert.fire_count })}
                        {alert.last_fired_at
                          ? ` · ${t('alertsPage.lastAt', {
                              when: new Date(alert.last_fired_at).toLocaleString(),
                            })}`
                          : ''}
                      </dd>
                    </div>
                  </dl>

                  <footer className={styles.cardFooter}>
                    <button
                      type="button"
                      className={styles.button}
                      onClick={() => {
                        void test(alert);
                      }}
                    >
                      {t('alertsPage.testSend')}
                    </button>
                    <button
                      type="button"
                      className={styles.button}
                      onClick={() => {
                        setEditing(alert);
                        setCreating(false);
                      }}
                    >
                      {t('alertsPage.edit')}
                    </button>
                    <button
                      type="button"
                      className={styles.button}
                      onClick={() => {
                        void remove(alert);
                      }}
                    >
                      {t('alertsPage.delete')}
                    </button>
                  </footer>
                </article>
              ))}
            </div>
          )
        ) : null}

        {tab === 'activity' ? <ActivityFeed events={events} alerts={alerts} /> : null}

        {tab === 'paper' ? <PaperPanel /> : null}
      </div>

      {creating || editing ? (
        <AlertForm
          alert={editing}
          setups={setups}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={() => {
            setCreating(false);
            setEditing(null);
            void refresh();
          }}
        />
      ) : null}
    </div>
  );
}

function ActivityFeed({ events, alerts }: { events: AlertEvent[]; alerts: Alert[] }) {
  const { t } = useTranslation();
  const names = new Map(alerts.map((alert) => [alert.id, alert.name]));

  if (events.length === 0) {
    return <p className={styles.placeholder}>{t('alertsPage.activityEmpty')}</p>;
  }

  return (
    <div className={styles.feed}>
      {events.map((event) => (
        <article key={event.id} className={styles.event}>
          <header className={styles.eventHeader}>
            <span className={styles.cardTitle}>
              {names.get(event.alert_id) ?? t('alertsPage.tabAlerts')}
            </span>
            <span className={styles.meta}>{new Date(event.created_at).toLocaleString()}</span>
            {event.merged_count > 1 ? (
              <span className={styles.badge}>
                {t('alertsPage.merged', { count: event.merged_count })}
              </span>
            ) : null}
            {event.quiet ? (
              <span className={styles.badge} title={t('alertsPage.quietBadgeTitle')}>
                {t('alertsPage.quietBadge')}
              </span>
            ) : null}
          </header>

          <pre className={styles.message}>{event.message}</pre>

          <div className={styles.deliveries}>
            {event.deliveries.map((delivery, index) => (
              <span
                key={`${delivery.kind}-${index}`}
                className={`${styles.delivery} ${styles[`state_${delivery.state}`] ?? ''}`}
                title={delivery.note || undefined}
              >
                <Icon
                  name={
                    delivery.state === 'sent'
                      ? 'check'
                      : delivery.state === 'failed'
                        ? 'close'
                        : 'clock'
                  }
                  size={11}
                />
                {delivery.kind}
                {delivery.latency_ms !== undefined && delivery.state === 'sent'
                  ? ` · ${delivery.latency_ms}ms`
                  : ''}
                {delivery.note ? ` · ${delivery.note}` : ''}
              </span>
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}
