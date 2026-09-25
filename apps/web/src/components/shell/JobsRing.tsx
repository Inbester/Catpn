/**
 * Jobs progress ring for the app rail: a percentage ring plus a queued-count
 * badge, shown on every page (SPEC §2).
 */

import styles from './AppRail.module.css';

const RADIUS = 9;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export interface JobsRingProps {
  progress: number;
  queued: number;
}

export function JobsRing({ progress, queued }: JobsRingProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(progress)));
  const offset = CIRCUMFERENCE * (1 - clamped / 100);

  return (
    <span className={styles.ring}>
      <svg viewBox="0 0 24 24" width={20} height={20} aria-hidden="true">
        <circle cx="12" cy="12" r={RADIUS} fill="none" stroke="var(--line)" strokeWidth={1.5} />
        {clamped > 0 ? (
          <circle
            cx="12"
            cy="12"
            r={RADIUS}
            fill="none"
            stroke="var(--accent)"
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={offset}
            transform="rotate(-90 12 12)"
          />
        ) : null}
      </svg>
      {clamped > 0 ? <span className={styles.ringLabel}>{clamped}</span> : null}
      {queued > 0 ? <span className={styles.badge}>{queued}</span> : null}
    </span>
  );
}
