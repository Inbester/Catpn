/**
 * Discover: enumerate rules, test them, report what survived (SPEC §3.2).
 *
 * The count of hits is meaningless without the two numbers beside it —
 * what an uncorrected search would have reported, and how many of the
 * survivors the procedure still allows to be chance. A search that finds
 * 40 rules where 1,300 would have passed uncorrected is a different
 * finding from one that finds 40 out of 45.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import { loadDocument, saveDocument } from '@/lib/autosave/store';
import * as researchApi from '../lib/api';
import {
  addChoice,
  choiceLabel,
  defaultChoices,
  inputOptions,
  MAX_INDICATORS,
  MAX_REQUIRED,
  paramProblem,
  parseSaved,
  pruneRequired,
  removeChoice,
  setInput,
  setParam,
  type CombineMode,
  type IndicatorChoice,
  type IndicatorSpec,
} from '../lib/indicators';
import { waitForJob } from '../lib/jobs';
import type { DiscoverPlan, DiscoverResult, ServerJob } from '../lib/types';
import styles from './research.module.css';

export interface DiscoverPanelProps {
  symbol: string;
  interval: string;
}

// One document for the picker, not per symbol: the indicators someone
// researches with travel with them from market to market.
const SAVED_SCOPE = 'discover';
const PLAN_DEBOUNCE_MS = 350;

const MODES: { key: CombineMode; label: string; hint: string }[] = [
  {
    key: 'any',
    label: 'Any combination',
    hint: 'Every rule the indicators allow, including ones that use a single indicator.',
  },
  {
    key: 'mix',
    label: 'At least two indicators',
    hint: 'Only rules where one indicator corroborates another. Price alone does not count.',
  },
  {
    key: 'require',
    label: 'Must include…',
    hint: 'Only rules that use every indicator you pick here — "RSI with MACD", by name.',
  },
];

export function DiscoverPanel({ symbol, interval }: DiscoverPanelProps) {
  const [specs, setSpecs] = useState<IndicatorSpec[]>([]);
  const [choices, setChoices] = useState<IndicatorChoice[]>(defaultChoices);
  const [mode, setMode] = useState<CombineMode>('any');
  const [required, setRequired] = useState<string[]>([]);
  const [conditions, setConditions] = useState(3);
  const [costPercent, setCostPercent] = useState(0.13);
  const restored = useRef(false);

  const [plan, setPlan] = useState<DiscoverPlan | null>(null);
  const [job, setJob] = useState<ServerJob | null>(null);
  const [result, setResult] = useState<DiscoverResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void researchApi
      .listIndicators()
      .then(setSpecs)
      .catch(() => {
        setError('Could not load the indicator list.');
      });
    let cancelled = false;
    void loadDocument<Record<string, unknown>>('research', SAVED_SCOPE)
      .then((data) => {
        if (cancelled) return;
        const saved = parseSaved(data);
        if (saved) {
          setChoices(saved.choices);
          setMode(saved.mode);
          setRequired(saved.required);
          setConditions(saved.conditions);
        }
      })
      .catch(() => undefined)
      .finally(() => {
        restored.current = true;
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // Saved like everything else, so a set of indicators built once is
    // still there tomorrow and on the other device.
    if (!restored.current) return;
    void saveDocument('research', SAVED_SCOPE, { choices, mode, required, conditions });
  }, [choices, mode, required, conditions]);

  const problems = useMemo(() => {
    const found: Record<string, string> = {};
    for (const choice of choices) {
      const spec = specs.find((item) => item.id === choice.id);
      for (const param of spec?.params ?? []) {
        const problem = paramProblem(param, choice.params[param.name] ?? param.default);
        if (problem) {
          found[choice.key] = problem;
          break;
        }
      }
    }
    return found;
  }, [choices, specs]);

  const request = useMemo(
    () => ({
      symbol,
      interval,
      indicators: choices,
      mix_indicators: mode === 'mix',
      require: mode === 'require' ? required : [],
      max_conditions: conditions,
    }),
    [symbol, interval, choices, mode, required, conditions],
  );

  const blocked = Object.keys(problems).length > 0 || (mode === 'require' && required.length === 0);

  useEffect(() => {
    if (blocked) {
      setPlan(null);
      return;
    }
    // Debounced: typing "21" into a length is two plans otherwise, and the
    // first is for a length of 2.
    const timer = setTimeout(() => {
      setError(null);
      researchApi
        .discoverPlan(request)
        .then(setPlan)
        .catch((caught: unknown) => {
          setPlan(null);
          setError(caught instanceof ApiError ? caught.message : 'Could not size the search.');
        });
    }, PLAN_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [request, blocked]);

  const update = (next: IndicatorChoice[]) => {
    setChoices(next);
    setRequired((current) => pruneRequired(current, next));
  };

  const toggleRequired = (key: string) => {
    setRequired((current) =>
      current.includes(key)
        ? current.filter((k) => k !== key)
        : current.length >= MAX_REQUIRED
          ? current
          : [...current, key],
    );
  };

  const run = async () => {
    setError(null);
    setResult(null);
    try {
      const started = await researchApi.startDiscover({ ...request, cost_percent: costPercent });
      setJob(started);
      const finished = await waitForJob(started.id, setJob);
      setJob(finished);
      if (finished.state === 'done' && finished.result) setResult(finished.result);
      else if (finished.state === 'failed') setError(finished.error ?? 'The search failed.');
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'The search could not start.');
    }
  };

  const running = job?.state === 'running' || job?.state === 'queued';
  const activeMode = MODES.find((item) => item.key === mode) ?? MODES[0]!;

  return (
    <div className={styles.stack}>
      <section className={styles.panel}>
        <header className={styles.panelHeader}>
          <span className={styles.panelTitle}>Indicators</span>
          <span className={styles.panelNote}>
            price is always included · {choices.length} of {MAX_INDICATORS}
          </span>
        </header>
        <div className={styles.panelBody}>
          {choices.length === 0 ? (
            <p className={styles.hint}>
              No indicators yet — the search would only look at price. Add one below.
            </p>
          ) : (
            <ul className={styles.indicatorList}>
              {choices.map((choice, index) => (
                <IndicatorRow
                  key={choice.key}
                  choice={choice}
                  index={index}
                  choices={choices}
                  specs={specs}
                  problem={problems[choice.key] ?? null}
                  disabled={running}
                  onParam={(name, value) => {
                    update(setParam(choices, choice.key, name, value));
                  }}
                  onInput={(input) => {
                    update(setInput(choices, choice.key, input));
                  }}
                  onRemove={() => {
                    update(removeChoice(choices, choice.key));
                  }}
                />
              ))}
            </ul>
          )}

          <label className={styles.field}>
            <span className={styles.label}>Add an indicator</span>
            <select
              className={styles.select}
              value=""
              disabled={running || choices.length >= MAX_INDICATORS || specs.length === 0}
              onChange={(event) => {
                if (event.target.value) update(addChoice(choices, specs, event.target.value));
              }}
            >
              <option value="">
                {choices.length >= MAX_INDICATORS ? `At most ${MAX_INDICATORS}` : 'Choose…'}
              </option>
              {specs.map((spec) => (
                <option key={spec.id} value={spec.id} title={spec.description}>
                  {spec.name} — {spec.description}
                </option>
              ))}
            </select>
            <span className={styles.hint}>
              The same indicator can be added more than once with different settings, and most can
              be applied to another indicator instead of price — an EMA of RSI, an SMA of volume.
            </span>
          </label>
        </div>
      </section>

      <section className={styles.panel}>
        <header className={styles.panelHeader}>
          <span className={styles.panelTitle}>Combine</span>
          <span className={styles.panelNote}>how a rule may mix the indicators above</span>
        </header>
        <div className={styles.panelBody}>
          <div className={styles.segmented} role="radiogroup" aria-label="Combination">
            {MODES.map((item) => (
              <button
                key={item.key}
                type="button"
                role="radio"
                aria-checked={mode === item.key}
                className={`${styles.segment} ${mode === item.key ? styles.segmentOn : ''}`}
                disabled={running}
                onClick={() => {
                  setMode(item.key);
                }}
              >
                {item.label}
              </button>
            ))}
          </div>
          <span className={styles.hint}>{activeMode.hint}</span>

          {mode === 'require' ? (
            <div className={styles.chips}>
              {choices.map((choice) => (
                <button
                  key={choice.key}
                  type="button"
                  aria-pressed={required.includes(choice.key)}
                  className={`${styles.chip} ${required.includes(choice.key) ? styles.chipOn : ''}`}
                  disabled={
                    running || (!required.includes(choice.key) && required.length >= MAX_REQUIRED)
                  }
                  onClick={() => {
                    toggleRequired(choice.key);
                  }}
                >
                  {choiceLabel(choices, specs, choice.key)}
                </button>
              ))}
              {required.length === 0 ? (
                <span className={styles.hint}>Pick up to {MAX_REQUIRED}.</span>
              ) : null}
            </div>
          ) : null}

          <div className={styles.field}>
            <span className={styles.label}>Conditions per rule</span>
            <div className={styles.segmented} role="radiogroup" aria-label="Conditions per rule">
              {[1, 2, 3].map((count) => (
                <button
                  key={count}
                  type="button"
                  role="radio"
                  aria-checked={conditions === count}
                  className={`${styles.segment} ${conditions === count ? styles.segmentOn : ''}`}
                  disabled={running}
                  onClick={() => {
                    setConditions(count);
                  }}
                >
                  {count}
                </button>
              ))}
            </div>
            <span className={styles.hint}>
              {conditions === 1
                ? 'One event per rule, nothing else required.'
                : `One event, plus up to ${conditions - 1} condition${conditions > 2 ? 's' : ''} that must also hold.`}{' '}
              Fewer conditions means fewer tests, and a lower bar for a finding to survive.
            </span>
          </div>

          <label className={styles.field}>
            <span className={styles.label}>Round-trip cost (%)</span>
            <input
              className={styles.input}
              type="number"
              step={0.01}
              min={0}
              value={costPercent}
              onChange={(event) => {
                const value = Number(event.target.value);
                if (Number.isFinite(value)) setCostPercent(value);
              }}
            />
            <span className={styles.hint}>
              Bitunix VIP0 taker both ways is 0.12% before slippage — more than the mean move many
              rules produce.
            </span>
          </label>

          {plan ? (
            <dl className={styles.planGrid}>
              <div>
                <dt>Series</dt>
                <dd className="num">{plan.series.length}</dd>
              </div>
              <div>
                <dt>Conditions</dt>
                <dd className="num">
                  {plan.primitives} · {plan.filters}F / {plan.triggers}T
                </dd>
              </div>
              <div>
                <dt>Raw combinations</dt>
                <dd className="num">{plan.raw_combinations.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Valid rules</dt>
                <dd className="num">
                  {plan.too_large ? '> ' : ''}
                  {plan.rules.toLocaleString()}
                </dd>
              </div>
              <div>
                <dt>Tests</dt>
                <dd className="num">
                  {plan.too_large ? '> ' : ''}
                  {plan.tests.toLocaleString()}
                </dd>
              </div>
            </dl>
          ) : null}

          {plan?.too_large ? (
            <p className={styles.warn} role="status">
              <Icon name="warning" size={12} /> More than {plan.max_rules.toLocaleString()} rules —
              too many for one search. Remove an indicator, require one, or allow fewer conditions
              per rule.
            </p>
          ) : null}

          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}

          <div className={styles.actions}>
            <button
              type="button"
              className={`${styles.button} ${styles.primary}`}
              disabled={running || !plan || plan.too_large || blocked || plan.rules === 0}
              onClick={() => {
                void run();
              }}
            >
              {running
                ? `Searching… ${Math.round(job?.percent ?? 0)}%`
                : plan && plan.rules === 0
                  ? 'No rules to test'
                  : `Run ${plan && !plan.too_large ? plan.tests.toLocaleString() : ''} tests`}
            </button>
            {running && job ? (
              <button
                type="button"
                className={styles.button}
                onClick={() => {
                  void researchApi.cancelJob(job.id);
                }}
              >
                Stop
              </button>
            ) : null}
          </div>

          {running && job ? (
            <div className={styles.progress}>
              <span className={styles.progressBar} style={{ width: `${job.percent}%` }} />
            </div>
          ) : null}
        </div>
      </section>

      {result ? <DiscoverResults result={result} /> : null}
    </div>
  );
}

interface IndicatorRowProps {
  choice: IndicatorChoice;
  index: number;
  choices: IndicatorChoice[];
  specs: IndicatorSpec[];
  problem: string | null;
  disabled: boolean;
  onParam: (name: string, value: number) => void;
  onInput: (input: string) => void;
  onRemove: () => void;
}

function IndicatorRow({
  choice,
  index,
  choices,
  specs,
  problem,
  disabled,
  onParam,
  onInput,
  onRemove,
}: IndicatorRowProps) {
  const spec = specs.find((item) => item.id === choice.id);
  const label = choiceLabel(choices, specs, choice.key);

  return (
    <li className={styles.indicatorRow}>
      <div className={styles.indicatorHead}>
        <span className={styles.indicatorName} title={spec?.description}>
          {label}
        </span>
        <button
          type="button"
          className={styles.iconButton}
          aria-label={`Remove ${label}`}
          disabled={disabled}
          onClick={onRemove}
        >
          <Icon name="close" size={12} />
        </button>
      </div>

      <div className={styles.indicatorSettings}>
        {spec?.params.map((param) => (
          <label key={param.name} className={styles.paramField}>
            <span className={styles.label}>{param.label}</span>
            <input
              className={styles.input}
              type="number"
              inputMode={param.integer ? 'numeric' : 'decimal'}
              min={param.min}
              max={param.max}
              step={param.integer ? 1 : 0.1}
              value={choice.params[param.name] ?? param.default}
              disabled={disabled}
              onChange={(event) => {
                onParam(param.name, event.target.value === '' ? NaN : Number(event.target.value));
              }}
            />
          </label>
        ))}

        {spec?.takes_input ? (
          <label className={styles.paramField}>
            <span className={styles.label}>Applied to</span>
            <select
              className={styles.select}
              value={choice.input}
              disabled={disabled}
              onChange={(event) => {
                onInput(event.target.value);
              }}
            >
              {inputOptions(choices, specs, index).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span className={styles.hint}>Reads the bars directly.</span>
        )}
      </div>

      {problem ? <span className={styles.rowError}>{problem}</span> : null}
    </li>
  );
}

function DiscoverResults({ result }: { result: DiscoverResult }) {
  const kept = result.hits.length;
  return (
    <section className={styles.panel}>
      <header className={styles.panelHeader}>
        <span className={styles.panelTitle}>Relationships</span>
        <span className={styles.panelNote}>
          {result.in_sample_bars.toLocaleString()} bars searched ·{' '}
          {result.out_of_sample_bars.toLocaleString()} held back
        </span>
      </header>

      <div className={styles.panelBody}>
        <div className={styles.verdictRow}>
          <span className={styles.kpiBig}>{result.hits_total.toLocaleString()}</span>
          <span className={styles.verdictText}>
            {result.hits_total === 0 ? (
              <>
                Nothing survived the correction. Across{' '}
                <span className="num">{result.tested.toLocaleString()}</span> tests, taking{' '}
                <span className="num">p ≤ 0.05</span> at face value would have handed back{' '}
                <span className="num">{result.significant_uncorrected.toLocaleString()}</span>{' '}
                &ldquo;findings&rdquo; — which is what chance alone produces at this many tests.
              </>
            ) : (
              <>
                rules survived out of <span className="num">{result.tested.toLocaleString()}</span>{' '}
                tests. An uncorrected search would have reported{' '}
                <span className="num">{result.significant_uncorrected.toLocaleString()}</span>.
                About <span className="num">{result.expected_false_hits.toFixed(1)}</span> of the
                survivors are still expected to be chance.
              </>
            )}
          </span>
        </div>

        {kept > 0 ? (
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Rule</th>
                  <th>Side</th>
                  <th>Horizon</th>
                  <th>Signals</th>
                  <th>Mean net</th>
                  <th>Win rate</th>
                  <th>p</th>
                  <th>Held-out mean</th>
                </tr>
              </thead>
              <tbody>
                {result.hits.map((hit) => (
                  <tr key={`${hit.rule_key}|${hit.side}|${hit.horizon}`}>
                    <td className={styles.ruleKey} title={hit.rule_key}>
                      {hit.rule_label || hit.rule_key}
                    </td>
                    <td>{hit.side}</td>
                    <td className="num">{hit.horizon} bars</td>
                    <td className="num">{hit.signals}</td>
                    <td className={`num ${hit.mean_net_percent >= 0 ? 'up' : 'down'}`}>
                      {hit.mean_net_percent >= 0 ? '+' : ''}
                      {hit.mean_net_percent.toFixed(3)}%
                    </td>
                    <td className="num">{(hit.win_rate * 100).toFixed(0)}%</td>
                    <td className="num">{hit.p_value.toExponential(1)}</td>
                    <td
                      className={`num ${
                        hit.out_of_sample_signals === 0
                          ? ''
                          : hit.out_of_sample_mean_percent >= 0
                            ? 'up'
                            : 'down'
                      }`}
                      title="Scored after the correction, on data no rule was chosen from"
                    >
                      {hit.out_of_sample_signals === 0
                        ? '—'
                        : `${hit.out_of_sample_mean_percent >= 0 ? '+' : ''}${hit.out_of_sample_mean_percent.toFixed(3)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        <p className={styles.hint}>
          <Icon name="warning" size={12} /> The held-out column is the only number here that was
          never part of choosing these rules. Read it first.
        </p>
      </div>
    </section>
  );
}
