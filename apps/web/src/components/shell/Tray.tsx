/**
 * The popover shell used by the Jobs tray and the active-alerts list.
 * Closes on Escape and on a click outside.
 */

import { useEffect, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Icon } from '@/components/Icon';
import styles from './Tray.module.css';

export interface TrayProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export function Tray({ title, onClose, children }: TrayProps) {
  const { t } = useTranslation();

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [onClose]);

  return (
    <>
      <div className={styles.backdrop} onClick={onClose} aria-hidden="true" />
      <div className={styles.tray} role="dialog" aria-label={title}>
        <div className={styles.header}>
          <span className={styles.title}>{title}</span>
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label={t('common.close')}
          >
            <Icon name="close" size={16} />
          </button>
        </div>
        <div className={styles.body}>{children}</div>
      </div>
    </>
  );
}
