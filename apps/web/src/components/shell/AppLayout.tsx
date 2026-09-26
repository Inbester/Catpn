/**
 * The application shell: rail, top bar with save status, and the routed page.
 */

import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { Icon } from '@/components/Icon';
import { useAuthStore } from '@/lib/auth/store';
import { applyTheme, readStoredTheme, DEFAULT_THEME } from '@/lib/theme';
import type { Theme } from '@/lib/api/types';

import { AlertsTray } from './AlertsTray';
import { AppRail, MENU_ITEMS } from './AppRail';
import { JobsTray } from './JobsTray';
import { SaveStatus } from './SaveStatus';
import { toRows, useActiveAlerts, watchActiveAlerts } from '@/features/alerts/lib/activeAlerts';
import { GlossaryTip } from '@/features/glossary/GlossaryTip';
import { watchJobs } from '@/features/research/lib/jobs';
import styles from './AppLayout.module.css';

function usePageTitle(): string {
  const { t } = useTranslation();
  const { pathname } = useLocation();

  const item = MENU_ITEMS.find((entry) => pathname.startsWith(entry.path));
  if (item) return t(item.labelKey);
  // Setups has no rail entry: SPEC §3.2 files it under Research, which is
  // phase 4, so until then it is reached from the picker in each header.
  if (pathname.startsWith('/setups')) return t('nav.setups');
  if (pathname.startsWith('/settings')) return t('nav.settings');
  if (pathname.startsWith('/account')) return t('nav.account');
  return t('app.name');
}

export function AppLayout() {
  const { t } = useTranslation();
  const title = usePageTitle();
  const [openTray, setOpenTray] = useState<'jobs' | 'alerts' | null>(null);

  // The rail's ring shows server jobs from every menu, so a search keeps
  // counting while the user is somewhere else. Polling lives here rather
  // than in the Research page for exactly that reason.
  useEffect(() => watchJobs(), []);
  // The bell was built in phase 0 with nothing behind it; these are the
  // alerts that are actually enabled.
  useEffect(() => watchActiveAlerts(), []);
  const activeAlerts = useActiveAlerts((state) => state.alerts);

  const user = useAuthStore((state) => state.user);
  const updatePreferences = useAuthStore((state) => state.updatePreferences);
  const [theme, setTheme] = useState<Theme>(
    () => user?.theme ?? readStoredTheme() ?? DEFAULT_THEME,
  );

  const toggleTheme = () => {
    const next: Theme = theme === 'graphite' ? 'paper' : 'graphite';
    setTheme(next);
    applyTheme(next);
    // Best effort: the local change already applied, so a failed sync is not
    // worth interrupting the user for.
    void updatePreferences({ theme: next }).catch(() => undefined);
  };

  return (
    <div className={styles.app}>
      <AppRail
        activeAlertCount={activeAlerts.length}
        onOpenJobs={() => {
          setOpenTray((current) => (current === 'jobs' ? null : 'jobs'));
        }}
        onOpenAlerts={() => {
          setOpenTray((current) => (current === 'alerts' ? null : 'alerts'));
        }}
      />

      <div className={styles.main}>
        <header className={styles.topbar}>
          <h1 className={styles.pageTitle}>{title}</h1>
          <div className={styles.topbarRight}>
            <SaveStatus />
            <button
              type="button"
              className={styles.themeToggle}
              onClick={toggleTheme}
              aria-label={t('theme.label')}
              title={theme === 'graphite' ? t('theme.paper') : t('theme.graphite')}
            >
              <Icon name={theme === 'graphite' ? 'sun' : 'moon'} size={18} />
            </button>
          </div>
        </header>

        <main className={styles.content}>
          <Outlet />
        </main>
      </div>

      {openTray === 'jobs' ? (
        <JobsTray
          onClose={() => {
            setOpenTray(null);
          }}
        />
      ) : null}
      {openTray === 'alerts' ? (
        <AlertsTray
          alerts={toRows(activeAlerts)}
          onClose={() => {
            setOpenTray(null);
          }}
        />
      ) : null}

      {/* Persian help on hover, app-wide: the interface is English, and the
          words it is made of are explained where they are read rather than
          in a glossary page nobody opens. */}
      <GlossaryTip />
    </div>
  );
}
