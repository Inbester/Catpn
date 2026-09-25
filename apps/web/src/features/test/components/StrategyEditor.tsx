/**
 * The strategy editor: Builder and Formula views over the same rules
 * (SPEC §3.2).
 *
 * Validation runs against the server on a debounce, so the Formula view
 * shows the engine's own verdict — including the character position of a
 * mistake — rather than a second, possibly divergent, client-side parser.
 */

import { useEffect, useMemo, useState } from 'react';

import { listFunctions, validateStrategy } from '../lib/api';
import type { ExitRules, FunctionReference, StrategyPayload } from '../lib/types';
import styles from './StrategyEditor.module.css';

const VALIDATE_DEBOUNCE_MS = 400;

export interface StrategyEditorProps {
  value: StrategyPayload;
  onChange: (value: StrategyPayload) => void;
  onValidity: (valid: boolean) => void;
}

type Tab = 'builder' | 'formula';

function NumberField({
  label,
  value,
  onChange,
  step = 1,
  min = 0,
  placeholder,
}: {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  step?: number;
  min?: number;
  placeholder?: string;
}) {
  return (
    <label className={styles.field}>
      <span className={styles.label}>{label}</span>
      <input
        className={styles.input}
        type="number"
        step={step}
        min={min}
        value={value ?? ''}
        placeholder={placeholder ?? 'off'}
        onChange={(event) => {
          const raw = event.target.value;
          onChange(raw === '' ? null : Number(raw));
        }}
      />
    </label>
  );
}

export function StrategyEditor({ value, onChange, onValidity }: StrategyEditorProps) {
  const [tab, setTab] = useState<Tab>('formula');
  const [validation, setValidation] = useState<{
    valid: boolean;
    error: string | null;
    position: number | null;
    version: string | null;
  }>({ valid: true, error: null, position: null, version: null });
  const [functions, setFunctions] = useState<FunctionReference[]>([]);

  useEffect(() => {
    listFunctions()
      .then(setFunctions)
      .catch(() => undefined);
  }, []);

  // Ask the engine, on a debounce, so typing stays responsive.
  useEffect(() => {
    const timer = setTimeout(() => {
      validateStrategy(value)
        .then((result) => {
          setValidation({
            valid: result.valid,
            error: result.error,
            position: result.position,
            version: result.version,
          });
          onValidity(result.valid);
        })
        .catch(() => {
          // A failed round trip is not a strategy error; leave the last
          // verdict in place rather than flashing a false problem.
        });
    }, VALIDATE_DEBOUNCE_MS);

    return () => {
      clearTimeout(timer);
    };
  }, [value, onValidity]);

  const setExits = (changes: Partial<ExitRules>) => {
    onChange({ ...value, exits: { ...value.exits, ...changes } });
  };

  const paramText = useMemo(
    () =>
      Object.entries(value.params)
        .map(([key, number]) => `${key} = ${number}`)
        .join('\n'),
    [value.params],
  );

  return (
    <div className={styles.editor}>
      <div className={styles.tabs}>
        <button
          type="button"
          className={`${styles.tab} ${tab === 'builder' ? styles.active : ''}`}
          onClick={() => {
            setTab('builder');
          }}
        >
          Builder
        </button>
        <button
          type="button"
          className={`${styles.tab} ${tab === 'formula' ? styles.active : ''}`}
          onClick={() => {
            setTab('formula');
          }}
        >
          Formula
        </button>
      </div>

      <label className={styles.field}>
        <span className={styles.label}>Name</span>
        <input
          className={styles.input}
          value={value.name}
          onChange={(event) => {
            onChange({ ...value, name: event.target.value });
          }}
        />
      </label>

      <label className={styles.field}>
        <span className={styles.label}>Long entry</span>
        <textarea
          className={`${styles.code} ${!validation.valid ? styles.invalid : ''}`}
          rows={2}
          spellCheck={false}
          value={value.long_entry ?? ''}
          placeholder="crossover(close, ema(close, 20))"
          onChange={(event) => {
            onChange({ ...value, long_entry: event.target.value || null });
          }}
        />
      </label>

      <label className={styles.field}>
        <span className={styles.label}>Short entry</span>
        <textarea
          className={`${styles.code} ${!validation.valid ? styles.invalid : ''}`}
          rows={2}
          spellCheck={false}
          value={value.short_entry ?? ''}
          placeholder="crossunder(close, ema(close, 20))"
          onChange={(event) => {
            onChange({ ...value, short_entry: event.target.value || null });
          }}
        />
      </label>

      {validation.error ? (
        <p className={styles.error} role="alert">
          {validation.error}
          {validation.position !== null ? ` (character ${validation.position + 1})` : ''}
        </p>
      ) : validation.version ? (
        <p className={styles.ok}>Valid · version {validation.version.slice(0, 12)}</p>
      ) : null}

      {tab === 'builder' ? (
        <>
          <div className={styles.section}>Exit and risk</div>
          <div className={styles.grid}>
            <NumberField
              label="ATR stop (× ATR)"
              value={value.exits.atr_stop_multiple}
              step={0.1}
              onChange={(v) => {
                setExits({ atr_stop_multiple: v });
              }}
            />
            <NumberField
              label="ATR length"
              value={value.exits.atr_length}
              min={1}
              onChange={(v) => {
                setExits({ atr_length: v ?? 14 });
              }}
            />
            <NumberField
              label="Take profit (R)"
              value={value.exits.take_profit_r}
              step={0.1}
              onChange={(v) => {
                setExits({ take_profit_r: v });
              }}
            />
            <NumberField
              label="Break even at (R)"
              value={value.exits.break_even_at_r}
              step={0.1}
              onChange={(v) => {
                setExits({ break_even_at_r: v });
              }}
            />
            <NumberField
              label="Trailing stop (× ATR)"
              value={value.exits.trailing_atr_multiple}
              step={0.1}
              onChange={(v) => {
                setExits({ trailing_atr_multiple: v });
              }}
            />
            <NumberField
              label="Time exit (bars)"
              value={value.exits.time_exit_bars}
              min={1}
              onChange={(v) => {
                setExits({ time_exit_bars: v });
              }}
            />
          </div>

          <label className={styles.check}>
            <input
              type="checkbox"
              checked={value.exits.exit_on_opposite}
              onChange={(event) => {
                setExits({ exit_on_opposite: event.target.checked });
              }}
            />
            Close when the opposite signal fires
          </label>

          <div className={styles.section}>Parameters</div>
          <textarea
            className={styles.code}
            rows={3}
            spellCheck={false}
            value={paramText}
            placeholder={'rsi_level = 30\nfast = 12'}
            onChange={(event) => {
              // One `name = number` per line. Lines that do not parse are
              // dropped rather than rejected, so the box stays editable.
              const params: Record<string, number> = {};
              for (const line of event.target.value.split('\n')) {
                const match = /^\s*([A-Za-z_]\w*)\s*=\s*(-?\d+(?:\.\d+)?)\s*$/.exec(line);
                if (match?.[1] && match[2]) params[match[1]] = Number(match[2]);
              }
              onChange({ ...value, params });
            }}
          />
        </>
      ) : (
        <>
          <div className={styles.section}>Available functions</div>
          <div className={styles.reference}>
            {functions.map((entry) => (
              <div key={entry.name} className={styles.referenceRow}>
                <span className={styles.referenceName}>
                  {entry.name}(
                  {entry.min_args === entry.max_args
                    ? entry.min_args
                    : `${entry.min_args}–${entry.max_args}`}
                  )
                </span>
                <span className={styles.referenceDoc}>{entry.doc}</span>
              </div>
            ))}
          </div>
          <p className={styles.ok}>
            Series: open, high, low, close, volume, hl2, hlc3, ohlc4. Operators: + - * / %,
            comparisons, and / or / not.
          </p>
        </>
      )}
    </div>
  );
}
