/**
 * Placeholder for a menu whose build phase has not arrived yet (SPEC §8).
 * It names the phase rather than pretending the feature is merely loading.
 */

import { useTranslation } from 'react-i18next';

import { Icon, type IconName } from '@/components/Icon';
import styles from './PhasePlaceholder.module.css';

export interface PhasePlaceholderProps {
  titleKey: string;
  icon: IconName;
  phase: number;
  note?: string;
}

export function PhasePlaceholder({ titleKey, icon, phase, note }: PhasePlaceholderProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.wrap}>
      <div className={styles.inner}>
        <Icon name={icon} size={32} className={styles.icon} />
        <h2 className={styles.title}>{t(titleKey)}</h2>
        <p className={styles.body}>{note ?? t('common.phasePlaceholder', { phase })}</p>
      </div>
    </div>
  );
}
