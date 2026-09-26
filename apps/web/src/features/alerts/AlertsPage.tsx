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

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import { useSetupsStore } from '@/features/setups/lib/store';
import { useActiveAlerts } from './lib/activeAlerts';
import * as alertsApi from './lib/api';
import { AlertForm } from './components/AlertForm';
import { REPEAT_LABELS, SOURCE_LABELS, type Alert, type AlertEvent } from './lib/types';
import { PaperPanel } from './components/PaperPanel';
import styles from './AlertsPage.module.css';

type Tab = 'alerts' | 'activity' | 'paper';

export function AlertsPage() {
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
      setError(caught instanceof ApiError ? caught.message : 'Could not load alerts.');
    }
  }, []);

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
      setError(caught instanceof ApiError ? caught.message : 'Could not delete that alert.');
    }
  };

  const test = async (alert: Alert) => {
    try {
      await alertsApi.testSend(alert.id);
      setTab('activity');
      await refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The test send failed.');
    }
  };

  return (
    <div className={styles.page}>
      <nav className={styles.tabs}>
        {(
          [
            ['alerts', `Alerts${alerts.length ? ` · ${alerts.length}` : ''}`],
            ['activity', 'Activity'],
            ['paper', 'Paper trading'],
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
            New alert
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
            <p className={styles.placeholder}>
              No alerts yet. An alert is evaluated on the server, so it fires whether or not this
              page is open.
            </p>
          ) : (
            <div className={styles.list}>
              {alerts.map((alert) => (
                <article key={alert.id} className={styles.card}>
                  <header className={styles.cardHeader}>
                    <span className={styles.cardTitle}>{alert.name}</span>
                    <span className={styles.badge}>{SOURCE_LABELS[alert.source]}</span>
                    <span className={styles.meta}>
                      {alert.symbol} · {alert.interval}
                    </span>
                    <span className={styles.spacer} />
                    {alert.enabled ? (
                      <span className={styles.on}>on</span>
                    ) : (
                      <span className={styles.off}>off</span>
                    )}
                  </header>

                  <dl className={styles.cardBody}>
                    <div>
                      <dt>Fires</dt>
                      <dd>
                        {REPEAT_LABELS[alert.repeat_mode]} ·{' '}
                        {alert.trigger_mode === 'bar_close' ? 'on bar close' : 'every tick'}
                      </dd>
                    </div>
                    <div>
                      <dt>Sends to</dt>
                      <dd>
                        {alert.destinations.length === 0
                          ? 'nowhere yet'
                          : alert.destinations.map((d) => d.kind).join(', ')}
                      </dd>
                    </div>
                    <div>
                      <dt>Quiet hours</dt>
                      <dd>
                        {alert.quiet_from_hour === null
                          ? 'none'
                          : `${alert.quiet_from_hour}:00–${alert.quiet_to_hour}:00, sent silently`}
                      </dd>
                    </div>
                    <div>
                      <dt>Fired</dt>
                      <dd>
                        {alert.fire_count} time{alert.fire_count === 1 ? '' : 's'}
                        {alert.last_fired_at
                          ? ` · last ${new Date(alert.last_fired_at).toLocaleString()}`
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
                      Test send
                    </button>
                    <button
                      type="button"
                      className={styles.button}
                      onClick={() => {
                        setEditing(alert);
                        setCreating(false);
                      }}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className={styles.button}
                      onClick={() => {
                        void remove(alert);
                      }}
                    >
                      Delete
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
  const names = new Map(alerts.map((alert) => [alert.id, alert.name]));

  if (events.length === 0) {
    return (
      <p className={styles.placeholder}>
        Nothing has fired yet. Every firing shows up here with what happened at each destination,
        including the ones a repeat rule suppressed.
      </p>
    );
  }

  return (
    <div className={styles.feed}>
      {events.map((event) => (
        <article key={event.id} className={styles.event}>
          <header className={styles.eventHeader}>
            <span className={styles.cardTitle}>{names.get(event.alert_id) ?? 'Alert'}</span>
            <span className={styles.meta}>{new Date(event.created_at).toLocaleString()}</span>
            {event.merged_count > 1 ? (
              <span className={styles.badge}>{event.merged_count} merged</span>
            ) : null}
            {event.quiet ? (
              <span className={styles.badge} title="Sent silently, not skipped">
                quiet hours
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
