/**
 * Settings (SPEC §3.6): the account-level things, in one place.
 *
 * Security comes first because it is what people come here for — turning
 * on 2FA, and reacting to a device they do not recognise. Exchange keys
 * are second: they belong to the account rather than to any one bot, one
 * key serves every bot, and this is where a person goes to connect an
 * outside service.
 */

import { useState } from 'react';

import { useAuthStore } from '@/lib/auth/store';
import { applyTheme, DEFAULT_THEME, readStoredTheme } from '@/lib/theme';
import type { Theme } from '@/lib/api/types';
import { KeysPanel } from './KeysPanel';
import { SecurityPanel } from './SecurityPanel';
import styles from './SettingsPage.module.css';

type Tab = 'security' | 'keys' | 'appearance';

const TABS: { key: Tab; label: string }[] = [
  { key: 'security', label: 'Security' },
  { key: 'keys', label: 'Exchange keys' },
  { key: 'appearance', label: 'Appearance' },
];

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>('security');

  return (
    <div className={styles.page}>
      <nav className={styles.tabs} role="tablist" aria-label="Settings">
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={tab === entry.key}
            className={tab === entry.key ? `${styles.tab} ${styles.tabActive}` : styles.tab}
            onClick={() => {
              setTab(entry.key);
            }}
          >
            {entry.label}
          </button>
        ))}
      </nav>

      <div className={styles.body}>
        {tab === 'security' ? <SecurityPanel /> : null}
        {tab === 'keys' ? <KeysPanel /> : null}
        {tab === 'appearance' ? <AppearancePanel /> : null}
      </div>
    </div>
  );
}

function AppearancePanel() {
  const user = useAuthStore((state) => state.user);
  const updatePreferences = useAuthStore((state) => state.updatePreferences);
  const [theme, setTheme] = useState<Theme>(
    () => user?.theme ?? readStoredTheme() ?? DEFAULT_THEME,
  );

  const choose = (next: Theme) => {
    setTheme(next);
    applyTheme(next);
    // Applied locally first, so the change is instant; a failed sync is
    // not worth interrupting someone for.
    void updatePreferences({ theme: next }).catch(() => undefined);
  };

  return (
    <div className={styles.panel}>
      <section className={styles.card}>
        <header className={styles.cardHeader}>
          <h3 className={styles.cardTitle}>Theme</h3>
        </header>
        <div className={styles.row}>
          {(['graphite', 'paper'] as const).map((option) => (
            <button
              key={option}
              type="button"
              className={theme === option ? styles.primary : styles.button}
              onClick={() => {
                choose(option);
              }}
            >
              {option === 'graphite' ? 'Graphite' : 'Paper'}
            </button>
          ))}
        </div>
        <p className={styles.note}>
          Graphite is the dark theme, Paper the light one. Charts keep their own up and down colours
          in both.
        </p>
      </section>
    </div>
  );
}
