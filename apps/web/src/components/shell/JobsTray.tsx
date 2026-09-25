/**
 * Jobs tray: Running / Queued / Paused / Finished (SPEC §2).
 *
 * The job runner lands in phase 4; until then this renders the real store,
 * which is empty, rather than a mock.
 */

import { useTranslation } from 'react-i18next';

import { Tray } from './Tray';
import styles from './Tray.module.css';
import { useJobsStore, type Job, type JobState } from './jobsStore';

const SECTIONS: Array<{ state: JobState; titleKey: string }> = [
  { state: 'running', titleKey: 'jobs.running' },
  { state: 'queued', titleKey: 'jobs.queued' },
  { state: 'paused', titleKey: 'jobs.paused' },
  { state: 'finished', titleKey: 'jobs.finished' },
];

export interface JobsTrayProps {
  onClose: () => void;
}

export function JobsTray({ onClose }: JobsTrayProps) {
  const { t } = useTranslation();
  const jobs = useJobsStore((state) => state.jobs);

  const byState = (state: JobState): Job[] => jobs.filter((job) => job.state === state);

  return (
    <Tray title={t('jobs.title')} onClose={onClose}>
      {jobs.length === 0 ? (
        <p className={styles.empty}>{t('jobs.empty')}</p>
      ) : (
        SECTIONS.map(({ state, titleKey }) => {
          const group = byState(state);
          if (group.length === 0) return null;
          return (
            <div key={state} className={styles.section}>
              <div className={styles.sectionTitle}>{t(titleKey)}</div>
              {group.map((job) => (
                <div key={job.id} className={styles.row}>
                  <span>{job.title}</span>
                  {job.state === 'running' ? (
                    <span className="num muted">{job.progress}%</span>
                  ) : null}
                </div>
              ))}
            </div>
          );
        })
      )}
    </Tray>
  );
}
