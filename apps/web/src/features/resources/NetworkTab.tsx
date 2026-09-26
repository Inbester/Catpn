/**
 * Resources → Network (SPEC §3.6, §9).
 *
 * A tunnel is imported, validated and tested here. What it may carry is
 * deliberately narrower than SPEC §3.6 reads on its own: exchange traffic
 * — market data, history downloads and orders — stays on the server,
 * because sending it through a personal exit from a region the venue
 * restricts is the circumvention SPEC §9 rules out. The locked features
 * are shown with that reason rather than hidden, since a control that is
 * silently absent looks like a missing feature.
 */

import { useCallback, useEffect, useState } from 'react';

import { Icon } from '@/components/Icon';
import { ApiError, api } from '@/lib/api/client';
import styles from './ResourcesPage.module.css';

interface TunnelSummary {
  endpoint: string;
  public_key: string;
  address: string[];
  dns: string[];
  allowed_ips: string[];
  keepalive: number | null;
  has_preshared_key: boolean;
}

interface Tunnel {
  id: string;
  label: string;
  enabled: boolean;
  priority: number;
  summary: TunnelSummary;
  last_tested_at: string | null;
  last_result: {
    state?: string;
    detail?: string;
    quality?: string | null;
    latency_ms?: number | null;
    jitter_ms?: number | null;
    loss_percent?: number | null;
    exit_ip?: string | null;
  };
}

interface Features {
  routable: string[];
  locked: Record<string, string>;
}

interface Validation {
  valid: boolean;
  errors: string[];
  warnings: string[];
  summary: TunnelSummary | null;
}

const FEATURE_LABELS: Record<string, string> = {
  alerts_delivery: 'Alert delivery',
  ai: 'AI',
  chart_data: 'Chart live data',
  research_download: 'Research history download',
  bot: 'Trading bot orders',
};

export function NetworkTab() {
  const [tunnels, setTunnels] = useState<Tunnel[]>([]);
  const [features, setFeatures] = useState<Features | null>(null);
  const [routes, setRoutes] = useState<Record<string, string[]>>({});
  const [config, setConfig] = useState('');
  const [label, setLabel] = useState('');
  const [validation, setValidation] = useState<Validation | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [rows, kinds, current] = await Promise.all([
        api.get<Tunnel[]>('/network/tunnels'),
        api.get<Features>('/network/features'),
        api.get<Record<string, string[]>>('/network/routes'),
      ]);
      setTunnels(rows);
      setFeatures(kinds);
      setRoutes(current);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not read the network setup.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Validated as it is typed, because the point of validation is to name
  // the mistake before anything is saved.
  useEffect(() => {
    if (config.trim() === '') {
      setValidation(null);
      return;
    }
    const timer = setTimeout(() => {
      void api
        .post<Validation>('/network/validate', { config })
        .then(setValidation)
        .catch(() => {
          setValidation(null);
        });
    }, 300);
    return () => {
      clearTimeout(timer);
    };
  }, [config]);

  const save = async () => {
    setError(null);
    try {
      await api.post('/network/tunnels', { label: label.trim() || 'Tunnel', config });
      setConfig('');
      setLabel('');
      setValidation(null);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not import that config.');
    }
  };

  const test = async (tunnel: Tunnel) => {
    setError(null);
    try {
      await api.post(`/network/tunnels/${tunnel.id}/test`);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The test could not run.');
    }
  };

  const remove = async (tunnel: Tunnel) => {
    await api.delete(`/network/tunnels/${tunnel.id}`).catch(() => undefined);
    await load();
  };

  const route = async (feature: string, tunnelId: string) => {
    setError(null);
    try {
      await api.put('/network/routes', {
        feature,
        tunnel_ids: tunnelId === '' ? [] : [tunnelId],
      });
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not set that route.');
    }
  };

  return (
    <div className={styles.body}>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}

      <section className={styles.panel}>
        <header className={styles.panelHeader}>
          <span className={styles.panelTitle}>Import a WireGuard config</span>
          <span className={styles.panelNote}>
            the private key is encrypted and never shown again
          </span>
        </header>
        <div className={styles.sliders}>
          <label className={styles.slider}>
            <span className={styles.sliderLabel}>Name</span>
            <input
              className={styles.deviceName}
              style={{ border: '1px solid var(--line)', borderRadius: 6, padding: '6px 10px' }}
              value={label}
              placeholder="Home"
              onChange={(event) => {
                setLabel(event.target.value);
              }}
            />
          </label>

          <label className={styles.slider}>
            <span className={styles.sliderLabel}>Config</span>
            <textarea
              rows={9}
              spellCheck={false}
              value={config}
              placeholder={
                '[Interface]\nPrivateKey = …\nAddress = 10.66.66.2/32\n\n[Peer]\nPublicKey = …\nEndpoint = host:51820\nAllowedIPs = 0.0.0.0/0'
              }
              onChange={(event) => {
                setConfig(event.target.value);
              }}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--text-xs)',
                padding: 'var(--space-3)',
                border: '1px solid var(--line)',
                borderRadius: 'var(--radius-md)',
                background: 'var(--bg)',
                color: 'var(--text)',
                resize: 'vertical',
              }}
            />
          </label>

          {validation ? (
            <div>
              {validation.errors.map((message) => (
                <p key={message} className={styles.error} style={{ marginBottom: 6 }}>
                  {message}
                </p>
              ))}
              {validation.warnings.map((message) => (
                <p key={message} className={styles.caution} style={{ border: 'none', padding: 0 }}>
                  <Icon name="warning" size={12} />
                  {message}
                </p>
              ))}
              {validation.valid && validation.summary ? (
                <p className={styles.caution} style={{ border: 'none', padding: 0 }}>
                  <Icon name="check" size={12} />
                  {validation.summary.endpoint} · {validation.summary.address.join(', ')}
                </p>
              ) : null}
            </div>
          ) : null}

          <div>
            <button
              type="button"
              className={styles.segment}
              style={{ border: '1px solid var(--line)', borderRadius: 8, height: 32 }}
              disabled={!validation?.valid}
              onClick={() => {
                void save();
              }}
            >
              Import
            </button>
          </div>
        </div>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelHeader}>
          <span className={styles.panelTitle}>Tunnels</span>
          <span className={styles.panelNote}>tested at most once every 30 seconds</span>
        </header>
        {tunnels.length === 0 ? (
          <p className={styles.placeholder}>No tunnels imported.</p>
        ) : (
          <div className={styles.routing}>
            {tunnels.map((tunnel) => (
              <div key={tunnel.id} className={styles.routeRow}>
                <span className={styles.routeLabel}>
                  {tunnel.label}
                  <span className={styles.routeNote}>
                    {tunnel.summary.endpoint} · {tunnel.summary.address.join(', ')}
                  </span>
                </span>

                <span className={styles.routeNote}>
                  {tunnel.last_result.state === 'unavailable'
                    ? 'not measurable here'
                    : (tunnel.last_result.quality ?? 'never tested')}
                </span>

                <span style={{ display: 'flex', gap: 'var(--space-2)' }}>
                  <button
                    type="button"
                    className={styles.segment}
                    style={{ border: '1px solid var(--line)', borderRadius: 8 }}
                    onClick={() => {
                      void test(tunnel);
                    }}
                  >
                    Test
                  </button>
                  <button
                    type="button"
                    className={styles.segment}
                    style={{ border: '1px solid var(--line)', borderRadius: 8 }}
                    onClick={() => {
                      void remove(tunnel);
                    }}
                  >
                    Remove
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className={styles.panel}>
        <header className={styles.panelHeader}>
          <span className={styles.panelTitle}>What goes through a tunnel</span>
          <span className={styles.panelNote}>exchange traffic does not</span>
        </header>
        <div className={styles.routing}>
          {features?.routable.map((feature) => (
            <div key={feature} className={styles.routeRow}>
              <span className={styles.routeLabel}>{FEATURE_LABELS[feature] ?? feature}</span>
              <select
                className={styles.segment}
                style={{ border: '1px solid var(--line)', borderRadius: 8, height: 30 }}
                value={routes[feature]?.[0] ?? ''}
                onChange={(event) => {
                  void route(feature, event.target.value);
                }}
              >
                <option value="">The server&rsquo;s own route</option>
                {tunnels.map((tunnel) => (
                  <option key={tunnel.id} value={tunnel.id}>
                    {tunnel.label}
                  </option>
                ))}
              </select>
              <span />
            </div>
          ))}

          {Object.entries(features?.locked ?? {}).map(([feature, reason]) => (
            <div key={feature} className={styles.routeRow}>
              <span className={styles.routeLabel}>
                {FEATURE_LABELS[feature] ?? feature}
                <span className={styles.routeNote}>always the server</span>
              </span>
              <span />
              <span className={styles.lock} title={reason}>
                <Icon name="lock" size={12} />
                {reason}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
