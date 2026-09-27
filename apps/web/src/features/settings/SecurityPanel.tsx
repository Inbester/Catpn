/**
 * Two-factor authentication and sessions (SPEC §3.6).
 *
 * This is not optional furniture. SPEC §3.5 requires 2FA before a bot can
 * be armed, so without this panel the trading bot cannot be used at all.
 *
 * The recovery codes are shown exactly once, and the panel says so before
 * showing them rather than after. A user who closes the dialog without
 * writing them down has locked themselves out of their own account on the
 * day they lose their phone.
 */

import { useCallback, useEffect, useState } from 'react';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import { useAuthStore } from '@/lib/auth/store';
import * as settingsApi from './lib/api';
import styles from './SettingsPage.module.css';

type Stage = 'idle' | 'scanning' | 'codes';

export function SecurityPanel() {
  const user = useAuthStore((state) => state.user);
  const bootstrap = useAuthStore((state) => state.bootstrap);

  const [stage, setStage] = useState<Stage>('idle');
  const [enrolment, setEnrolment] = useState<settingsApi.TotpStart | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [sessions, setSessions] = useState<settingsApi.SessionRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadSessions = useCallback(async () => {
    try {
      setSessions(await settingsApi.listSessions());
    } catch {
      // A failed session list must not hide the 2FA controls, which are
      // the reason most people open this page.
      setSessions([]);
    }
  }, []);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  const say = (caught: unknown, fallback: string) =>
    setError(caught instanceof ApiError ? caught.message : fallback);

  const begin = async () => {
    setBusy(true);
    setError(null);
    try {
      setEnrolment(await settingsApi.startTotp());
      setStage('scanning');
    } catch (caught) {
      say(caught, 'Could not start enrolment.');
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await settingsApi.confirmTotp(code.trim());
      setCodes(result.recovery_codes);
      setStage('codes');
      setCode('');
      await bootstrap();
    } catch (caught) {
      say(caught, 'That code was not accepted.');
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    setError(null);
    try {
      await settingsApi.disableTotp(password, code.trim());
      setPassword('');
      setCode('');
      await bootstrap();
    } catch (caught) {
      say(caught, 'Could not turn it off.');
    } finally {
      setBusy(false);
    }
  };

  const signOutEverywhere = async () => {
    setBusy(true);
    try {
      await settingsApi.revokeOtherSessions();
      // Revoking every session includes this one, so the store has to be
      // told rather than left believing it is still signed in.
      await bootstrap();
    } catch (caught) {
      say(caught, 'Could not sign out everywhere.');
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
          <h3 className={styles.cardTitle}>Two-factor authentication</h3>
          {user?.totp_enabled ? (
            <span className={styles.onBadge}>On</span>
          ) : (
            <span className={styles.offBadge}>Off</span>
          )}
        </header>

        <p className={styles.note}>
          Required before a trading bot can be armed, before the kill switch, and before a risk
          limit can be raised.
        </p>

        {user?.totp_enabled ? (
          <div className={styles.form}>
            <p className={styles.note}>
              To turn it off, confirm with your password and a current code. Any bot that is armed
              will refuse to act without it.
            </p>
            <label className={styles.field}>
              <span className={styles.label}>Password</span>
              <input
                className={styles.input}
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                }}
              />
            </label>
            <label className={styles.field}>
              <span className={styles.label}>Code</span>
              <input
                className={styles.input}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={10}
                value={code}
                onChange={(event) => {
                  setCode(event.target.value);
                }}
              />
            </label>
            <button
              type="button"
              className={styles.danger}
              disabled={busy || !password || code.length < 6}
              onClick={() => void disable()}
            >
              Turn off
            </button>
          </div>
        ) : stage === 'idle' ? (
          <button
            type="button"
            className={styles.primary}
            disabled={busy}
            onClick={() => void begin()}
          >
            Set up
          </button>
        ) : null}

        {stage === 'scanning' && enrolment ? (
          <div className={styles.form}>
            <p className={styles.note}>
              Scan this with an authenticator app, then type the six digits it shows.
            </p>
            <div
              className={styles.qr}
              // The SVG comes from our own API, rendered by a QR library
              // from a URI we built. It is not user input.
              dangerouslySetInnerHTML={{ __html: enrolment.qr_svg }}
            />
            <p className={styles.secret}>
              Can’t scan? Enter this key instead: <code>{enrolment.secret}</code>
            </p>
            <label className={styles.field}>
              <span className={styles.label}>Code from the app</span>
              <input
                className={styles.input}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={10}
                value={code}
                onChange={(event) => {
                  setCode(event.target.value);
                }}
              />
            </label>
            <div className={styles.row}>
              <button
                type="button"
                className={styles.primary}
                disabled={busy || code.length < 6}
                onClick={() => void confirm()}
              >
                Confirm
              </button>
              <button
                type="button"
                className={styles.button}
                onClick={() => {
                  setStage('idle');
                  setEnrolment(null);
                  setCode('');
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        ) : null}

        {stage === 'codes' ? (
          <div className={styles.form}>
            <p className={styles.warn}>
              <Icon name="warning" size={13} />
              Write these down now. They are shown once and never again. Each one signs you in if
              you lose your phone, and each works only once.
            </p>
            <ul className={styles.codes}>
              {codes.map((recovery) => (
                <li key={recovery}>
                  <code>{recovery}</code>
                </li>
              ))}
            </ul>
            <div className={styles.row}>
              <button
                type="button"
                className={styles.button}
                onClick={() => {
                  void navigator.clipboard?.writeText(codes.join('\n'));
                }}
              >
                Copy
              </button>
              <button
                type="button"
                className={styles.primary}
                onClick={() => {
                  setStage('idle');
                  setCodes([]);
                  setEnrolment(null);
                }}
              >
                I have written them down
              </button>
            </div>
          </div>
        ) : null}
      </section>

      <section className={styles.card}>
        <header className={styles.cardHeader}>
          <h3 className={styles.cardTitle}>Signed-in devices</h3>
          <span className={styles.meta}>{sessions.length}</span>
        </header>

        {sessions.length === 0 ? (
          <p className={styles.note}>No other devices.</p>
        ) : (
          <ul className={styles.sessions}>
            {sessions.map((session) => (
              <li key={session.id} className={styles.sessionRow}>
                <span className={styles.sessionName}>
                  {session.device_label ?? session.user_agent ?? 'Unknown device'}
                </span>
                <span className={styles.meta}>
                  last used {new Date(session.last_used_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        )}

        <p className={styles.note}>
          If you think someone else has your password, this is the first thing to do. It signs out
          every device, including this one.
        </p>
        <button
          type="button"
          className={styles.danger}
          disabled={busy}
          onClick={() => void signOutEverywhere()}
        >
          Sign out everywhere
        </button>
      </section>
    </div>
  );
}
