/**
 * The pipeline as six chips (SPEC §3.2).
 *
 * Every stage is always shown, including the ones not started: the point of
 * the row is how far a Setup has got, which you cannot read from the passed
 * stages alone.
 */

import { PIPELINE_STAGES, STAGE_LABELS, STAGE_NAMES, stageStatus } from '../lib/types';
import type { Setup, StageStatus } from '../lib/types';
import styles from './setups.module.css';

const STATUS_CLASS: Record<StageStatus, string | undefined> = {
  passed: styles.stagePassed,
  running: styles.stageRunning,
  failed: styles.stageFailed,
  not_started: styles.stageIdle,
};

const STATUS_WORD: Record<StageStatus, string> = {
  passed: 'passed',
  running: 'running',
  failed: 'failed',
  not_started: 'not started',
};

export function StageChips({ setup, size = 'sm' }: { setup: Setup; size?: 'sm' | 'md' }) {
  return (
    <span className={`${styles.stages} ${size === 'md' ? styles.stagesMd : ''}`}>
      {PIPELINE_STAGES.map((stage) => {
        const status = stageStatus(setup, stage);
        return (
          <span
            key={stage}
            className={`${styles.stage} ${STATUS_CLASS[status] ?? ''}`}
            title={`${STAGE_NAMES[stage]}: ${STATUS_WORD[status]}`}
          >
            {STAGE_LABELS[stage]}
          </span>
        );
      })}
    </span>
  );
}
