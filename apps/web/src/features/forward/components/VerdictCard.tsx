/**
 * The verdict and the checks behind it (SPEC §3.3).
 *
 * The chip states the conclusion, but the checks are what make it
 * arguable: a user can see which part held up rather than being handed a
 * single score to trust.
 */

import { Icon } from '@/components/Icon';
import { VERDICT_LABELS, type Check, type VerdictKey } from '../lib/types';
import styles from './forward.module.css';

export interface VerdictCardProps {
  verdict: VerdictKey;
  headline: string;
  explanation: string;
  checks: Check[];
}

const CHIP_CLASS: Record<VerdictKey, string> = {
  holds_up: styles.chipOk as string,
  holds_up_weaker: styles.chipWarn as string,
  outside_range: styles.chipFail as string,
  too_few_trades: styles.chipWarn as string,
};

const CHECK_CLASS: Record<Check['severity'], string> = {
  ok: styles.checkOk as string,
  warn: styles.checkWarn as string,
  fail: styles.checkFail as string,
};

export function VerdictCard({ verdict, headline, explanation, checks }: VerdictCardProps) {
  return (
    <section className={styles.panel}>
      <div className={styles.verdict}>
        <span className={`${styles.chip} ${CHIP_CLASS[verdict]}`}>
          <Icon name={verdict === 'outside_range' ? 'warning' : 'check'} size={14} />
          {VERDICT_LABELS[verdict]}
        </span>

        <div className={styles.verdictBody}>
          <h2 className={styles.headline}>{headline}</h2>
          <p className={styles.explanation}>{explanation}</p>

          <div className={styles.checks}>
            {checks.map((check) => (
              <span
                key={check.key}
                className={`${styles.check} ${CHECK_CLASS[check.severity]}`}
                title={check.detail}
              >
                <Icon name={check.severity === 'ok' ? 'check' : 'warning'} size={12} />
                {check.label}
                <span className={styles.checkDetail}>{check.detail}</span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
