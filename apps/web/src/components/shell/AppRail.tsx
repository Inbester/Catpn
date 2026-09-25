/**
 * The app rail: logo, the seven menus, the jobs ring, the active-alerts bell,
 * settings and account (SPEC §2, D1).
 *
 * Menu order is fixed by D1 and must not be rearranged:
 * Chart · Research · Test · Alerts · Trading bot · Resources · AI
 */

import { NavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { Icon, type IconName } from '@/components/Icon';
import styles from './AppRail.module.css';
import { JobsRing } from './JobsRing';
import { selectQueuedCount, selectRingProgress, useJobsStore } from './jobsStore';

interface MenuItem {
  path: string;
  icon: IconName;
  labelKey: string;
}

export const MENU_ITEMS: readonly MenuItem[] = [
  { path: '/chart', icon: 'chart', labelKey: 'nav.chart' },
  { path: '/research', icon: 'research', labelKey: 'nav.research' },
  { path: '/test', icon: 'test', labelKey: 'nav.test' },
  { path: '/alerts', icon: 'alerts', labelKey: 'nav.alerts' },
  { path: '/bot', icon: 'bot', labelKey: 'nav.bot' },
  { path: '/resources', icon: 'resources', labelKey: 'nav.resources' },
  { path: '/ai', icon: 'ai', labelKey: 'nav.ai' },
] as const;

export interface AppRailProps {
  activeAlertCount?: number;
  onOpenJobs?: () => void;
  onOpenAlerts?: () => void;
}

export function AppRail({ activeAlertCount = 0, onOpenJobs, onOpenAlerts }: AppRailProps) {
  const { t } = useTranslation();
  const jobs = useJobsStore((state) => state.jobs);
  const progress = selectRingProgress(jobs);
  const queued = selectQueuedCount(jobs);

  return (
    <nav className={styles.rail} aria-label={t('app.name')}>
      <div className={styles.logo} aria-hidden="true">
        Q
      </div>

      {MENU_ITEMS.map((item) => (
        <NavLink
          key={item.path}
          to={item.path}
          className={({ isActive }) => `${styles.item} ${isActive ? styles.active : ''}`}
          title={t(item.labelKey)}
        >
          <Icon name={item.icon} />
          <span className="sr-only">{t(item.labelKey)}</span>
        </NavLink>
      ))}

      <div className={styles.spacer} />

      <button
        type="button"
        className={styles.item}
        onClick={onOpenJobs}
        title={t('jobs.title')}
        aria-label={t('jobs.title')}
      >
        <JobsRing progress={progress} queued={queued} />
      </button>

      <button
        type="button"
        className={styles.item}
        onClick={onOpenAlerts}
        title={t('alerts.title')}
        aria-label={t('alerts.title')}
      >
        <Icon name="alerts" />
        {activeAlertCount > 0 ? <span className={styles.badge}>{activeAlertCount}</span> : null}
      </button>

      <NavLink
        to="/settings"
        className={({ isActive }) => `${styles.item} ${isActive ? styles.active : ''}`}
        title={t('nav.settings')}
      >
        <Icon name="settings" />
        <span className="sr-only">{t('nav.settings')}</span>
      </NavLink>

      <NavLink
        to="/account"
        className={({ isActive }) => `${styles.item} ${isActive ? styles.active : ''}`}
        title={t('nav.account')}
      >
        <Icon name="account" />
        <span className="sr-only">{t('nav.account')}</span>
      </NavLink>
    </nav>
  );
}
