/**
 * Resources → Network (SPEC §3.6, §9).
 *
 * Tunnels here are real: each runs as a WireGuard client on the server,
 * Test sends real requests through it, and alert delivery uses the one
 * the user put first. The page therefore shows what the server is doing —
 * running, idle, failed and why — rather than only what was imported.
 *
 * What a tunnel may carry is deliberately narrower than SPEC §3.6 reads on
 * its own: exchange traffic — market data, history downloads and orders —
 * stays on the server, because sending it through a personal exit from a
 * region the venue restricts is the circumvention SPEC §9 rules out. The
 * locked features are shown with that reason rather than hidden, since a
 * control that is silently absent looks like a missing feature.
 */

import { useCallback, useEffect, useState } from 'react';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import * as network from './lib/network';
import page from './ResourcesPage.module.css';
import styles from './NetworkTab.module.css';

const FEATURE_LABELS: Record<string, string> = {
  alerts_delivery: 'Alert delivery',
  ai: 'AI',
  chart_data: 'Chart live data',
  research_download: 'Research history download',
  bot: 'Trading bot orders',
};

const FEATURE_NOTES: Record<string, string> = {
  alerts_delivery: 'Telegram and webhook messages',
  ai: 'used once the AI menu is built',
};

// Alert delivery can start a tunnel in the background, so the states on
// this page go stale without anyone touching it.
const REFRESH_MS = 15_000;

type Tone = 'good' | 'fair' | 'bad' | 'none';

function stateTone(state: network.TunnelState): Tone {
  if (state === 'running') return 'good';
  if (state === 'failed') return 'bad';
  return 'none';
}

function qualityTone(quality: network.TestResult['quality']): Tone {
  if (quality === 'good') return 'good';
  if (quality === 'fair') return 'fair';
  if (quality === 'poor' || quality === 'down') return 'bad';
  return 'none';
}

export function NetworkTab() {
  const [engine, setEngine] = useState<network.Engine | null>(null);
  const [tunnels, setTunnels] = useState<network.Tunnel[]>([]);
  const [features, setFeatures] = useState<network.Features | null>(null);
  const [routes, setRoutes] = useState<Record<string, string[]>>({});
  const [config, setConfig] = useState('');
  const [label, setLabel] = useState('');
  const [validation, setValidation] = useState<network.Validation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const say = (caught: unknown, fallback: string) => {
    setError(caught instanceof ApiError ? caught.message : fallback);
  };

  const load = useCallback(async () => {
    try {
      const [state, rows, kinds, current] = await Promise.all([
        network.getEngine(),
        network.listTunnels(),
        network.getFeatures(),
        network.getRoutes(),
      ]);
      setEngine(state);
      setTunnels(rows);
      setFeatures(kinds);
      setRoutes(current);
    } catch (caught) {
      say(caught, 'Could not read the network setup.');
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        void network
          .listTunnels()
          .then(setTunnels)
          .catch(() => undefined);
      }
    }, REFRESH_MS);
    return () => {
      clearInterval(timer);
    };
  }, [load]);

  // Validated as it is typed, because the point of validation is to name
  // the mistake before anything is saved.
  useEffect(() => {
    if (config.trim() === '') {
      setValidation(null);
      return;
    }
    const timer = setTimeout(() => {
      void network
        .validate(config)
        .then(setValidation)
        .catch(() => {
          setValidation(null);
        });
    }, 300);
    return () => {
      clearTimeout(timer);
    };
  }, [config]);

  const run = async (key: string, action: () => Promise<unknown>, fallback: string) => {
    setBusy(key);
    setError(null);
    try {
      await action();
      await load();
    } catch (caught) {
      say(caught, fallback);
    } finally {
      setBusy(null);
    }
  };

  const save = () =>
    run(
      'import',
      async () => {
        await network.importTunnel(label.trim() || 'Tunnel', config);
        setConfig('');
        setLabel('');
        setValidation(null);
      },
      'Could not import that config.',
    );

  const toggle = (tunnel: network.Tunnel) =>
    run(
      tunnel.id,
      () => network.updateTunnel(tunnel.id, { enabled: !tunnel.enabled }),
      'Could not switch that tunnel.',
    );

  const rename = (tunnel: network.Tunnel, next: string) => {
    const trimmed = next.trim();
    if (trimmed === '' || trimmed === tunnel.label) return;
    void run(
      tunnel.id,
      () => network.updateTunnel(tunnel.id, { label: trimmed }),
      'Could not rename it.',
    );
  };

  const test = (tunnel: network.Tunnel) =>
    run(tunnel.id, () => network.testTunnel(tunnel.id), 'The test could not run.');

  const remove = (tunnel: network.Tunnel) => {
    if (!window.confirm(`Remove ${tunnel.label}? Its config and private key are deleted.`)) return;
    void run(tunnel.id, () => network.removeTunnel(tunnel.id), 'Could not remove it.');
  };

  const route = (feature: string, primary: string, fallback: string) =>
    run(
      feature,
      () => network.setRoute(feature, network.routeIds(primary, fallback)),
      'Could not set that route.',
    );

  const nameOf = (id: string) => tunnels.find((tunnel) => tunnel.id === id)?.label ?? 'removed';

  return (
    <div className={page.body}>
      {engine ? <EngineBanner engine={engine} /> : null}

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}

      <section className={page.panel}>
        <header className={page.panelHeader}>
          <span className={page.panelTitle}>Tunnels</span>
          <span className={page.panelNote}>tested at most once every 30 seconds</span>
        </header>
        {tunnels.length === 0 ? (
          <p className={page.placeholder}>No tunnels imported.</p>
        ) : (
          <div className={styles.tunnels}>
            {tunnels.map((tunnel) => (
              <TunnelRow
                key={tunnel.id}
                tunnel={tunnel}
                busy={busy === tunnel.id}
                canRun={engine?.available ?? false}
                onToggle={() => void toggle(tunnel)}
                onRename={(next) => {
                  rename(tunnel, next);
                }}
                onTest={() => void test(tunnel)}
                onRemove={() => {
                  remove(tunnel);
                }}
              />
            ))}
          </div>
        )}
      </section>

      <section className={page.panel}>
        <header className={page.panelHeader}>
          <span className={page.panelTitle}>What goes through a tunnel</span>
          <span className={page.panelNote}>exchange traffic never does</span>
        </header>
        <div className={styles.routes}>
          {features?.routable.map((feature) => {
            const [primary = '', fallback = ''] = routes[feature] ?? [];
            return (
              <div key={feature} className={styles.route}>
                <span className={styles.routeName}>
                  {FEATURE_LABELS[feature] ?? feature}
                  {FEATURE_NOTES[feature] ? (
                    <span className={styles.meta}>{FEATURE_NOTES[feature]}</span>
                  ) : null}
                </span>
                <div className={styles.routeChoices}>
                  <label className={styles.field}>
                    <span className={styles.label}>First choice</span>
                    <select
                      className={styles.select}
                      value={primary}
                      disabled={busy === feature}
                      onChange={(event) => {
                        void route(feature, event.target.value, fallback);
                      }}
                    >
                      <option value="">The server&rsquo;s own route</option>
                      {tunnels.map((tunnel) => (
                        <option key={tunnel.id} value={tunnel.id}>
                          {tunnel.label}
                          {tunnel.enabled ? '' : ' (off)'}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className={styles.field}>
                    <span className={styles.label}>If that is down</span>
                    <select
                      className={styles.select}
                      value={fallback}
                      disabled={busy === feature || primary === ''}
                      onChange={(event) => {
                        void route(feature, primary, event.target.value);
                      }}
                    >
                      <option value="">The server&rsquo;s own route</option>
                      {tunnels
                        .filter((tunnel) => tunnel.id !== primary)
                        .map((tunnel) => (
                          <option key={tunnel.id} value={tunnel.id}>
                            {tunnel.label}
                            {tunnel.enabled ? '' : ' (off)'}
                          </option>
                        ))}
                    </select>
                  </label>
                  {primary !== '' ? (
                    <span className={`${styles.meta} ${styles.routeSentence}`}>
                      {fallback !== ''
                        ? `${nameOf(primary)}, then ${nameOf(fallback)}, then the server.`
                        : `${nameOf(primary)}, then the server if it is down.`}{' '}
                      Each delivery records which way it went.
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })}

          {Object.entries(features?.locked ?? {}).map(([feature, reason]) => (
            <div key={feature} className={styles.route}>
              <span className={styles.routeName}>
                {FEATURE_LABELS[feature] ?? feature}
                <span className={styles.meta}>always the server</span>
              </span>
              <span className={styles.locked}>
                <Icon name="lock" size={12} />
                {reason}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className={page.panel}>
        <header className={page.panelHeader}>
          <span className={page.panelTitle}>Import a WireGuard config</span>
          <span className={page.panelNote}>the private key is encrypted and never shown again</span>
        </header>
        <div className={styles.form}>
          <label className={styles.field}>
            <span className={styles.label}>Name</span>
            <input
              className={styles.input}
              value={label}
              maxLength={120}
              placeholder="Home"
              onChange={(event) => {
                setLabel(event.target.value);
              }}
            />
          </label>

          <label className={styles.field}>
            <span className={styles.label}>Config (the contents of the .conf file)</span>
            <textarea
              className={styles.textarea}
              rows={9}
              spellCheck={false}
              value={config}
              placeholder={
                '[Interface]\nPrivateKey = …\nAddress = 10.66.66.2/32\nDNS = 1.1.1.1\n\n[Peer]\nPublicKey = …\nEndpoint = host:51820\nAllowedIPs = 0.0.0.0/0'
              }
              onChange={(event) => {
                setConfig(event.target.value);
              }}
            />
          </label>

          {validation ? (
            <ul className={styles.messages}>
              {validation.errors.map((message) => (
                <li key={message} className={styles.messageError}>
                  {message}
                </li>
              ))}
              {validation.warnings.map((message) => (
                <li key={message} className={styles.messageWarn}>
                  <Icon name="warning" size={12} />
                  {message}
                </li>
              ))}
              {validation.valid && validation.summary ? (
                <li className={styles.messageOk}>
                  <Icon name="check" size={12} />
                  {validation.summary.endpoint} · {validation.summary.address.join(', ')}
                </li>
              ) : null}
            </ul>
          ) : null}

          <div className={styles.row}>
            <button
              type="button"
              className={styles.primary}
              disabled={!validation?.valid || busy === 'import'}
              onClick={() => void save()}
            >
              Import
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function EngineBanner({ engine }: { engine: network.Engine }) {
  if (!engine.available) {
    return (
      <p className={`${styles.banner} ${styles.bannerDown}`} role="status">
        <Icon name="warning" size={14} />
        <span>
          Tunnels cannot run on this server. {engine.detail} Alerts are sent from the server until
          then.
        </span>
      </p>
    );
  }
  return (
    <p className={`${styles.banner} ${styles.bannerReady}`} role="status">
      <Icon name="check" size={14} />
      <span>
        <strong>WireGuard is ready.</strong> Each tunnel runs on the server and only carries the
        features you route through it.{' '}
        {engine.amnezia
          ? 'AmneziaWG configs are supported too.'
          : 'AmneziaWG configs need the AmneziaWG build installed.'}
      </span>
    </p>
  );
}

interface TunnelRowProps {
  tunnel: network.Tunnel;
  busy: boolean;
  canRun: boolean;
  onToggle: () => void;
  onRename: (next: string) => void;
  onTest: () => void;
  onRemove: () => void;
}

function TunnelRow({ tunnel, busy, canRun, onToggle, onRename, onTest, onRemove }: TunnelRowProps) {
  const [name, setName] = useState(tunnel.label);
  useEffect(() => {
    setName(tunnel.label);
  }, [tunnel.label]);

  const result = tunnel.last_result;
  const tested = tunnel.last_tested_at ? new Date(tunnel.last_tested_at).toLocaleString() : null;
  const summary = network.describeResult(result);
  // The live failure, when it says something the last test did not: why
  // it would not start, or what a real send ran into since.
  const failure =
    tunnel.state === 'failed' && tunnel.last_error && tunnel.last_error !== summary
      ? tunnel.last_error
      : null;

  return (
    <div className={styles.tunnel}>
      <label className={styles.switch} title={tunnel.enabled ? 'Switch off' : 'Switch on'}>
        <input
          type="checkbox"
          role="switch"
          aria-label={`${tunnel.label} on`}
          checked={tunnel.enabled}
          disabled={busy}
          onChange={onToggle}
        />
        <span className={styles.switchTrack} />
      </label>

      <div className={styles.tunnelMain}>
        <span className={styles.tunnelName}>
          <input
            className={`${page.deviceName} ${styles.nameInput}`}
            aria-label="Tunnel name"
            value={name}
            maxLength={120}
            onChange={(event) => {
              setName(event.target.value);
            }}
            onBlur={() => {
              onRename(name);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') event.currentTarget.blur();
            }}
          />
          <span className={styles.badge} data-tone={stateTone(tunnel.state)}>
            {network.STATE_LABELS[tunnel.state]}
          </span>
          {tunnel.enabled && result.state === 'ok' && result.quality ? (
            <span className={styles.badge} data-tone={qualityTone(result.quality)}>
              {result.quality}
            </span>
          ) : null}
          {tunnel.enabled && result.state === 'failed' ? (
            <span className={styles.badge} data-tone="bad">
              no traffic
            </span>
          ) : null}
        </span>
        <span className={styles.meta}>
          {tunnel.summary.endpoint} · {tunnel.summary.address.join(', ')}
        </span>
        <span className={styles.result}>
          {summary}
          {tested ? ` — ${tested}` : ''}
        </span>
        {failure ? <span className={styles.reason}>{failure}</span> : null}
      </div>

      <div className={styles.row}>
        <button
          type="button"
          className={styles.button}
          disabled={busy || !canRun || !tunnel.enabled}
          title={tunnel.enabled ? undefined : 'Switch it on to test it'}
          onClick={onTest}
        >
          {busy ? 'Testing…' : 'Test'}
        </button>
        <button type="button" className={styles.danger} disabled={busy} onClick={onRemove}>
          Remove
        </button>
      </div>
    </div>
  );
}
