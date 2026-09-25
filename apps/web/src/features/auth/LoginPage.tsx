/**
 * Sign in / create account, including the TOTP step.
 */

import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { ApiError } from '@/lib/api/client';
import { useAuthStore } from '@/lib/auth/store';
import styles from './LoginPage.module.css';

type Mode = 'signin' | 'register';

export function LoginPage() {
  const { t } = useTranslation();
  const status = useAuthStore((state) => state.status);
  const login = useAuthStore((state) => state.login);
  const register = useAuthStore((state) => state.register);
  const verifyMfa = useAuthStore((state) => state.verifyMfa);

  const [mode, setMode] = useState<Mode>('signin');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const needsMfa = status === 'mfa-required';

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);

    try {
      if (needsMfa) {
        await verifyMfa(code);
      } else if (mode === 'register') {
        await register(email, displayName, password);
      } else {
        await login(email, password);
      }
    } catch (caught) {
      setError(
        caught instanceof ApiError || caught instanceof Error
          ? caught.message
          : t('auth.genericError'),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.brand}>
          <span className={styles.logo} aria-hidden="true">
            Q
          </span>
          <span className={styles.brandName}>{t('app.name')}</span>
        </div>

        {needsMfa ? (
          <>
            <h2 className={styles.heading}>{t('auth.twoFactor')}</h2>
            <p className={styles.hint}>{t('auth.twoFactorHint')}</p>
          </>
        ) : (
          <h2 className={styles.heading}>
            {mode === 'register' ? t('auth.createAccount') : t('auth.signIn')}
          </h2>
        )}

        {error ? (
          <div className={styles.error} role="alert">
            {error}
          </div>
        ) : null}

        <form
          onSubmit={(event) => {
            void submit(event);
          }}
          noValidate
        >
          {needsMfa ? (
            <div className={styles.field}>
              <label className={styles.label} htmlFor="code">
                {t('auth.twoFactor')}
              </label>
              <input
                id="code"
                className={`${styles.input} ${styles.code}`}
                value={code}
                onChange={(event) => {
                  setCode(event.target.value);
                }}
                autoComplete="one-time-code"
                inputMode="text"
                autoFocus
                required
              />
            </div>
          ) : (
            <>
              {mode === 'register' ? (
                <div className={styles.field}>
                  <label className={styles.label} htmlFor="displayName">
                    {t('auth.displayName')}
                  </label>
                  <input
                    id="displayName"
                    className={styles.input}
                    value={displayName}
                    onChange={(event) => {
                      setDisplayName(event.target.value);
                    }}
                    autoComplete="name"
                    required
                  />
                </div>
              ) : null}

              <div className={styles.field}>
                <label className={styles.label} htmlFor="email">
                  {t('auth.email')}
                </label>
                <input
                  id="email"
                  type="email"
                  className={styles.input}
                  value={email}
                  onChange={(event) => {
                    setEmail(event.target.value);
                  }}
                  autoComplete="email"
                  required
                />
              </div>

              <div className={styles.field}>
                <label className={styles.label} htmlFor="password">
                  {t('auth.password')}
                </label>
                <input
                  id="password"
                  type="password"
                  className={styles.input}
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                  }}
                  autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                  required
                />
                {mode === 'register' ? (
                  <p className={styles.hint} style={{ marginTop: 'var(--space-2)' }}>
                    {t('auth.passwordRules')}
                  </p>
                ) : null}
              </div>
            </>
          )}

          <button type="submit" className={styles.submit} disabled={busy}>
            {busy
              ? t('auth.signingIn')
              : needsMfa
                ? t('auth.verify')
                : mode === 'register'
                  ? t('auth.createAccount')
                  : t('auth.signIn')}
          </button>
        </form>

        {needsMfa ? null : (
          <p className={styles.footer}>
            {mode === 'register' ? t('auth.haveAccount') : t('auth.noAccount')}{' '}
            <button
              type="button"
              className={styles.link}
              onClick={() => {
                setMode(mode === 'register' ? 'signin' : 'register');
                setError(null);
              }}
            >
              {mode === 'register' ? t('auth.signIn') : t('auth.createAccount')}
            </button>
          </p>
        )}
      </div>
    </div>
  );
}
