/**
 * Discover: enumerate rules, test them, report what survived (SPEC §3.2).
 *
 * The count of hits is meaningless without the two numbers beside it —
 * what an uncorrected search would have reported, and how many of the
 * survivors the procedure still allows to be chance. A search that finds
 * 40 rules where 1,300 would have passed uncorrected is a different
 * finding from one that finds 40 out of 45.
 */

import { useCallback, useEffect, useState } from 'react';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import * as researchApi from '../lib/api';
import { waitForJob } from '../lib/jobs';
import type { DiscoverPlan, DiscoverResult, ServerJob, SourceInfo } from '../lib/types';
import styles from './research.module.css';

export interface DiscoverPanelProps {
  symbol: string;
  interval: string;
}

export function DiscoverPanel({ symbol, interval }: DiscoverPanelProps) {
  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [chosen, setChosen] = useState<string[]>(['price', 'ema', 'rsi']);
  const [mixIndicators, setMixIndicators] = useState(false);
  const [costPercent, setCostPercent] = useState(0.13);

  const [plan, setPlan] = useState<DiscoverPlan | null>(null);
  const [job, setJob] = useState<ServerJob | null>(null);
  const [result, setResult] = useState<DiscoverResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void researchApi
      .listSources()
      .then(setSources)
      .catch(() => {
        // The chips fall back to the defaults already chosen.
      });
  }, []);

  const refreshPlan = useCallback(async () => {
    setError(null);
    try {
      setPlan(
        await researchApi.discoverPlan({
          symbol,
          interval,
          sources: chosen,
          mix_indicators: mixIndicators,
        }),
      );
    } catch (caught) {
      setPlan(null);
      setError(caught instanceof ApiError ? caught.message : 'Could not size the search.');
    }
  }, [symbol, interval, chosen, mixIndicators]);

  useEffect(() => {
    void refreshPlan();
  }, [refreshPlan]);

  const toggle = (key: string) => {
    if (key === 'price') return; // Divergence is defined against price.
    setChosen((current) =>
      current.includes(key) ? current.filter((k) => k !== key) : [...current, key],
    );
  };

  const run = async () => {
    setError(null);
    setResult(null);
    try {
      const started = await researchApi.startDiscover({
        symbol,
        interval,
        sources: chosen,
        mix_indicators: mixIndicators,
        cost_percent: costPercent,
      });
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

  return (
    <div className={styles.stack}>
      <section className={styles.panel}>
        <header className={styles.panelHeader}>
          <span className={styles.panelTitle}>Sources</span>
          <span className={styles.panelNote}>price is always included</span>
        </header>
        <div className={styles.panelBody}>
          <div className={styles.chips}>
            {sources.map((source) => (
              <button
                key={source.key}
                type="button"
                className={`${styles.chip} ${chosen.includes(source.key) ? styles.chipOn : ''}`}
                disabled={source.key === 'price'}
                onClick={() => {
                  toggle(source.key);
                }}
                title={source.lines.join(' · ')}
              >
                {source.label}
              </button>
            ))}
          </div>

          <label className={styles.check}>
            <input
              type="checkbox"
              checked={mixIndicators}
              onChange={(event) => {
                setMixIndicators(event.target.checked);
              }}
            />
            Only rules that mix two indicators
            <span className={styles.hint}>
              Price is a source but not an indicator, so price crossing an EMA is one
              indicator&rsquo;s evidence and does not qualify.
            </span>
          </label>

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
                <dd className="num">{plan.rules.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Tests</dt>
                <dd className="num">{plan.tests.toLocaleString()}</dd>
              </div>
            </dl>
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
              disabled={running || !plan}
              onClick={() => {
                void run();
              }}
            >
              {running
                ? `Searching… ${Math.round(job?.percent ?? 0)}%`
                : `Run ${plan ? plan.tests.toLocaleString() : ''} tests`}
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
                      {hit.rule_key}
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
