/**
 * Exchange API keys (SPEC §3.6).
 *
 * The user connects their own key and trades their own account; the
 * platform never holds funds (SPEC §9).
 *
 * The server's IP is shown **above** the form, not beside it and not
 * after. A key pasted before that address is whitelisted will simply be
 * refused, and the user will not know why — so the order on screen is the
 * order of the work: whitelist first, then paste.
 *
 * What comes back is a label, the last four characters and a fingerprint.
 * The secret is never returned to anyone, including the person who typed
 * it, so there is nothing here to reveal.
 */

import { useCallback, useEffect, useState } from 'react';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import * as settingsApi from './lib/api';
import styles from './SettingsPage.module.css';

export function KeysPanel() {
  const [serverIp, setServerIp] = useState('');
  const [keys, setKeys] = useState<settingsApi.ExchangeKey[]>([]);
  const [label, setLabel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      const result = await settingsApi.listKeys();
      setServerIp(result.server_ip);
      setKeys(result.keys);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not read your keys.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const add = async () => {
    setBusy(true);
    setError(null);
    try {
      await settingsApi.addKey({ label, api_key: apiKey, api_secret: apiSecret });
      // Cleared immediately: there is no reason for the secret to sit in
      // a form field after it has been sealed.
      setLabel('');
      setApiKey('');
      setApiSecret('');
      setAdding(false);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'That key was not accepted.');
    } finally {
      setBusy(false);
    }
  };

  const remove = async (key: settingsApi.ExchangeKey) => {
    setBusy(true);
    setError(null);
    try {
      await settingsApi.deleteKey(key.id);
      await load();
    } catch (caught) {
      // The server names the bot still using it, which is what the user
      // needs to know to act.
      setError(caught instanceof ApiError ? caught.message : 'Could not delete that key.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.panel}>
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}

      <section className={styles.card}>
        <header className={styles.cardHeader}>
          <h3 className={styles.cardTitle}>Before you add a key</h3>
        </header>
        <p className={styles.note}>
          Orders are sent from this server and nowhere else. Whitelist this address on the key at
          the exchange first — a key without it is refused.
        </p>
        {serverIp ? (
          <div className={styles.ipRow}>
            <code className={styles.ip}>{serverIp}</code>
            <button
              type="button"
              className={styles.button}
              onClick={() => {
                void navigator.clipboard?.writeText(serverIp);
              }}
            >
              Copy
            </button>
          </div>
        ) : (
          <p className={styles.warn}>
            <Icon name="warning" size={13} />
            This server has no static IP configured, so no key can be added. Set EXCHANGE_STATIC_IP
            and restart.
          </p>
        )}
        <p className={styles.note}>
          Give the key <strong>trading permission only</strong>. A key that can withdraw is refused
          — this platform never moves your funds.
        </p>
      </section>

      <section className={styles.card}>
        <header className={styles.cardHeader}>
          <h3 className={styles.cardTitle}>Connected keys</h3>
          <span className={styles.spacer} />
          {!adding && serverIp ? (
            <button
              type="button"
              className={styles.primary}
              onClick={() => {
                setAdding(true);
              }}
            >
              Add a key
            </button>
          ) : null}
        </header>

        {keys.length === 0 && !adding ? (
          <p className={styles.note}>No keys yet.</p>
        ) : (
          <ul className={styles.keys}>
            {keys.map((key) => (
              <li key={key.id} className={styles.keyRow}>
                <div className={styles.keyMain}>
                  <span className={styles.keyLabel}>{key.label}</span>
                  <span className={styles.meta}>
                    {key.exchange} · ····{key.last_four}
                  </span>
                </div>
                <span className={styles.meta} title="A stable id for this key. Not the key.">
                  {key.fingerprint}
                </span>
                <span className={styles.spacer} />
                {key.ip_whitelist.includes(serverIp) ? (
                  <span className={styles.onBadge}>pinned</span>
                ) : (
                  <span className={styles.offBadge} title="No longer whitelisted for this server">
                    not pinned
                  </span>
                )}
                <button
                  type="button"
                  className={styles.danger}
                  disabled={busy}
                  onClick={() => void remove(key)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}

        {adding ? (
          <div className={styles.form}>
            <label className={styles.field}>
              <span className={styles.label}>Name</span>
              <input
                className={styles.input}
                value={label}
                placeholder="Main"
                onChange={(event) => {
                  setLabel(event.target.value);
                }}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.label}>API key</span>
              <input
                className={styles.input}
                autoComplete="off"
                spellCheck={false}
                value={apiKey}
                onChange={(event) => {
                  setApiKey(event.target.value);
                }}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.label}>API secret</span>
              <input
                className={styles.input}
                type="password"
                autoComplete="off"
                value={apiSecret}
                onChange={(event) => {
                  setApiSecret(event.target.value);
                }}
              />
              <span className={styles.hint}>
                Checked with the exchange before it is stored, then encrypted. It is never shown
                again, to anyone.
              </span>
            </label>
            <div className={styles.row}>
              <button
                type="button"
                className={styles.primary}
                disabled={busy || !label || apiKey.length < 8 || apiSecret.length < 8}
                onClick={() => void add()}
              >
                {busy ? 'Checking with the exchange…' : 'Add key'}
              </button>
              <button
                type="button"
                className={styles.button}
                onClick={() => {
                  setAdding(false);
                  setApiKey('');
                  setApiSecret('');
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
