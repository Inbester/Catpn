/**
 * Active-alerts popover, grouped by setup with next check times (SPEC §2).
 * The alert evaluator arrives in phase 5.
 */

import { useTranslation } from 'react-i18next';

import { Tray } from './Tray';
import styles from './Tray.module.css';

export interface ActiveAlert {
  id: string;
  setupName: string;
  description: string;
  nextCheckAt: string | null;
}

export interface AlertsTrayProps {
  alerts?: ActiveAlert[];
  onClose: () => void;
}

export function AlertsTray({ alerts = [], onClose }: AlertsTrayProps) {
  const { t } = useTranslation();

  const bySetup = alerts.reduce<Record<string, ActiveAlert[]>>((groups, alert) => {
    (groups[alert.setupName] ??= []).push(alert);
    return groups;
  }, {});

  return (
    <Tray title={t('alerts.title')} onClose={onClose}>
      {alerts.length === 0 ? (
        <p className={styles.empty}>{t('alerts.empty')}</p>
      ) : (
        Object.entries(bySetup).map(([setupName, group]) => (
          <div key={setupName} className={styles.section}>
            <div className={styles.sectionTitle}>{setupName}</div>
            {group.map((alert) => (
              <div key={alert.id} className={styles.row}>
                <span>{alert.description}</span>
                {alert.nextCheckAt ? <span className="num muted">{alert.nextCheckAt}</span> : null}
              </div>
            ))}
          </div>
        ))
      )}
    </Tray>
  );
}
