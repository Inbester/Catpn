/**
 * Save as setup (SPEC §3.2).
 *
 * The dialog shows the whole bundle before it is locked, because that is
 * the promise a Setup makes: these exact rules, this market, this sizing,
 * these costs — not whatever the draft says next week.
 *
 * The Bot checkbox is absent rather than disabled: the server refuses to
 * set it until paper trading passes, so offering it here would be a
 * control that cannot work.
 */

import { useState } from 'react';

import { ApiError } from '@/lib/api/client';
import * as setupsApi from './lib/api';
import { useSetupsStore } from './lib/store';
import { SETUP_COLORS, type Setup } from './lib/types';
import styles from './SaveSetupDialog.module.css';

export interface SaveSetupDialogProps {
  strategyId: string;
  strategyName: string;
  strategyVersion: string;
  symbol: string;
  interval: string;
  marginPercent: number;
  leverage: number;
  marginMode: 'isolated' | 'cross';
  makerFee: number;
  takerFee: number;
  /** The run this Setup is being saved from, so a number can be traced back. */
  sourceRunId?: string | null;
  /** Max drawdown seen in that run, offered as the starting budget. */
  observedDrawdownPercent?: number | null;
  onClose: () => void;
  onSaved?: (setup: Setup) => void;
}

export function SaveSetupDialog({
  strategyId,
  strategyName,
  strategyVersion,
  symbol,
  interval,
  marginPercent,
  leverage,
  marginMode,
  makerFee,
  takerFee,
  sourceRunId = null,
  observedDrawdownPercent = null,
  onClose,
  onSaved,
}: SaveSetupDialogProps) {
  const adopt = useSetupsStore((state) => state.adopt);

  const [name, setName] = useState(`${symbol} ${interval} ${strategyName}`.slice(0, 120));
  const [color, setColor] = useState<string>(SETUP_COLORS[0]);
  const [budget, setBudget] = useState<string>(
    // Two decimals, not one: rounding -99.98 to -100.0 would quietly hand
    // back room the run never had, and the help text below says the opposite.
    observedDrawdownPercent !== null && observedDrawdownPercent < 0
      ? observedDrawdownPercent.toFixed(2)
      : '',
  );
  const [uses, setUses] = useState({
    use_in_backtest: true,
    use_in_forward: true,
    use_in_paper: false,
    use_in_alerts: false,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const exposure = marginPercent * leverage;
  const budgetValue = budget.trim() === '' ? null : Number(budget);
  const budgetInvalid =
    budgetValue !== null &&
    (!Number.isFinite(budgetValue) || budgetValue >= 0 || budgetValue < -100);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const setup = await setupsApi.createSetup({
        name: name.trim(),
        color,
        strategy_id: strategyId,
        symbol,
        interval,
        margin_percent: marginPercent,
        leverage,
        margin_mode: marginMode,
        maker_fee: makerFee,
        taker_fee: takerFee,
        max_drawdown_budget_percent: budgetValue,
        source_run_id: sourceRunId,
        ...uses,
      });
      adopt(setup);
      onSaved?.(setup);
      onClose();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The setup could not be saved.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={styles.backdrop}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-label="Save as setup">
        <header className={styles.header}>
          <span className={styles.title}>Save as setup</span>
          <span className={styles.note}>locks this version</span>
        </header>

        <div className={styles.body}>
          <label className={styles.field}>
            <span className={styles.label}>Name</span>
            <input
              className={styles.input}
              value={name}
              maxLength={120}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          </label>

          <div className={styles.field}>
            <span className={styles.label}>Colour</span>
            <div className={styles.colors}>
              {SETUP_COLORS.map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-label={`Colour ${option}`}
                  aria-pressed={option === color}
                  className={`${styles.color} ${option === color ? styles.colorActive : ''}`}
                  style={{ background: option }}
                  onClick={() => {
                    setColor(option);
                  }}
                />
              ))}
            </div>
          </div>

          <dl className={styles.bundle}>
            <div>
              <dt>Strategy</dt>
              <dd>
                {strategyName} · <span className="num">{strategyVersion.slice(0, 12)}</span>
              </dd>
            </div>
            <div>
              <dt>Market</dt>
              <dd className="num">
                {symbol} · {interval}
              </dd>
            </div>
            <div>
              <dt>Position</dt>
              <dd className="num">
                {marginPercent}% × {leverage}× {marginMode}
              </dd>
            </div>
            <div>
              <dt>Exposure</dt>
              <dd className="num" title="Margin share times leverage: what the setup controls">
                {exposure.toFixed(0)}% of equity
              </dd>
            </div>
            <div>
              <dt>Fees</dt>
              <dd className="num">
                maker {makerFee} · taker {takerFee}
              </dd>
            </div>
          </dl>

          <label className={styles.field}>
            <span className={styles.label}>Max drawdown budget (%)</span>
            <input
              className={styles.input}
              type="number"
              step={0.5}
              max={-0.1}
              min={-100}
              placeholder="e.g. -25"
              value={budget}
              onChange={(event) => {
                setBudget(event.target.value);
              }}
            />
            <span className={styles.help}>
              {observedDrawdownPercent !== null
                ? `The run drew down ${observedDrawdownPercent.toFixed(2)}%. A budget below that leaves no room.`
                : 'Negative, or leave empty for no budget.'}
            </span>
          </label>

          <fieldset className={styles.uses}>
            <legend className={styles.label}>Use it in</legend>
            {(
              [
                ['use_in_backtest', 'Backtest'],
                ['use_in_forward', 'Forward'],
                ['use_in_paper', 'Paper'],
                ['use_in_alerts', 'Alerts'],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className={styles.check}>
                <input
                  type="checkbox"
                  checked={uses[key]}
                  onChange={(event) => {
                    setUses((current) => ({ ...current, [key]: event.target.checked }));
                  }}
                />
                {label}
              </label>
            ))}
            <p className={styles.locked}>
              Bot stays locked until paper trading passes (SPEC §3.3).
            </p>
          </fieldset>

          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}
        </div>

        <footer className={styles.footer}>
          <button type="button" className={styles.button} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={`${styles.button} ${styles.primary}`}
            disabled={busy || name.trim() === '' || budgetInvalid}
            onClick={() => {
              void save();
            }}
          >
            {busy ? 'Saving…' : 'Save setup'}
          </button>
        </footer>
      </div>
    </div>
  );
}
