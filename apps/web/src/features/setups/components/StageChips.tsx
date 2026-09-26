/**
 * The pipeline as six chips (SPEC §3.2).
 *
 * Every stage is always shown, including the ones not started: the point of
 * the row is how far a Setup has got, which you cannot read from the passed
 * stages alone.
 */

import { useTranslation } from 'react-i18next';

import { PIPELINE_STAGES, stageStatus } from '../lib/types';
import type { Setup, StageStatus } from '../lib/types';
import styles from './setups.module.css';

const STATUS_CLASS: Record<StageStatus, string | undefined> = {
  passed: styles.stagePassed,
  running: styles.stageRunning,
  failed: styles.stageFailed,
  not_started: styles.stageIdle,
};

export function StageChips({ setup, size = 'sm' }: { setup: Setup; size?: 'sm' | 'md' }) {
  const { t } = useTranslation();

  return (
    <span className={`${styles.stages} ${size === 'md' ? styles.stagesMd : ''}`}>
      {PIPELINE_STAGES.map((stage) => {
        const status = stageStatus(setup, stage);
        return (
          <span
            key={stage}
            className={`${styles.stage} ${STATUS_CLASS[status] ?? ''}`}
            title={`${t(`setups.stage.${stage}`)}: ${t(`setups.stageStatus.${status}`)}`}
          >
            {t(`setups.stageShort.${stage}`)}
          </span>
        );
      })}
    </span>
  );
}
