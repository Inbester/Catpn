/**
 * The top-bar save indicator: "Saved", "Saving…" or "Offline" (SPEC §2).
 */

import { useTranslation } from 'react-i18next';

import { useAutosaveStore, type SaveStatus as Status } from '@/lib/autosave/store';
import styles from './SaveStatus.module.css';

const LABEL_KEYS: Record<Status, string> = {
  saved: 'save.saved',
  saving: 'save.saving',
  offline: 'save.offline',
  error: 'save.error',
  conflict: 'save.conflict',
};

export function SaveStatus() {
  const { t } = useTranslation();
  const status = useAutosaveStore((state) => state.status);
  const pendingCount = useAutosaveStore((state) => state.pendingCount);
  const lastError = useAutosaveStore((state) => state.lastError);

  const showsPending = pendingCount > 0 && status !== 'saved';

  return (
    <span className={styles.status} role="status" aria-live="polite" title={lastError ?? undefined}>
      <span className={`${styles.dot} ${styles[status]}`} aria-hidden="true" />
      {t(LABEL_KEYS[status])}
      {showsPending ? (
        <span className="muted">· {t('save.pendingChanges', { count: pendingCount })}</span>
      ) : null}
    </span>
  );
}
