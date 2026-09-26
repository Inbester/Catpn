/**
 * Resources: where work runs (SPEC §3.6).
 *
 * The page exists because "run it faster" has two different answers. A
 * Discover search is worth sending to whichever machine has cores to
 * spare. An alert is not a performance question at all — it has to fire
 * when the browser is closed, so it only ever runs on the server.
 *
 * Those locks are shown as locks, with their reason, rather than as
 * missing options. A control that silently does nothing is worse than no
 * control.
 */

import { useCallback, useEffect, useState } from 'react';

import { Icon } from '@/components/Icon';
import { ApiError } from '@/lib/api/client';
import * as resourcesApi from './lib/api';
import { detectLocal, workerCount } from './lib/detect';
import { NetworkTab } from './NetworkTab';
import type { ComputeFeature, ComputeSettings, ComputeSource } from './lib/api';
import styles from './ResourcesPage.module.css';

const FEATURES: { key: ComputeFeature; label: string; note: string }[] = [
  { key: 'chart_data', label: 'Chart data', note: 'candles, indicators and drawings' },
  { key: 'research', label: 'Research', note: 'Discover searches and study sweeps' },
  { key: 'alerts', label: 'Alerts', note: 'evaluated on bar close' },
  { key: 'ai', label: 'AI', note: 'scope not defined yet' },
  { key: 'bot', label: 'Trading bot', note: 'order traffic' },
];

const SOURCES: { key: ComputeSource; label: string }[] = [
  { key: 'server', label: 'Server' },
  { key: 'local', label: 'This computer' },
  { key: 'auto', label: 'Auto' },
];

type Tab = 'compute' | 'network';

export function ResourcesPage() {
  const [tab, setTab] = useState<Tab>('compute');
  const [settings, setSettings] = useState<ComputeSettings | null>(null);
  const [jobs, setJobs] = useState<resourcesApi.JobHistoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [current, history] = await Promise.all([
        resourcesApi.getCompute(),
        resourcesApi.jobHistory().catch(() => []),
      ]);
      setSettings(current);
      setJobs(history);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not read compute settings.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Detected once per visit and sent up, so the card can show what this
  // machine reports without asking the browser again on every render.
  useEffect(() => {
    void detectLocal()
      .then((profile) => resourcesApi.updateCompute({ local_profile: profile }))
      .then(setSettings)
      .catch(() => {
        // Detection is a convenience; the page works without it.
      });
  }, []);

  const save = async (update: resourcesApi.ComputeUpdate) => {
    setBusy(true);
    setError(null);
    try {
      setSettings(await resourcesApi.updateCompute(update));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not save that choice.');
    } finally {
      setBusy(false);
    }
  };

  if (!settings) {
    return (
      <div className={styles.page}>
        <p className={styles.placeholder}>{error ?? 'Reading compute settings…'}</p>
      </div>
    );
  }

  const { server, local_profile: local } = settings;
  const workers = workerCount(local.cores, settings.cpu_share_percent);

  return (
    <div className={styles.page}>
      <nav className={styles.tabs}>
        {(
          [
            ['compute', 'Compute'],
            ['network', 'Network'],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`${styles.tab} ${tab === key ? styles.active : ''}`}
            onClick={() => {
              setTab(key);
            }}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === 'network' ? <NetworkTab /> : null}

      {tab === 'compute' ? (
        <div className={styles.body}>
          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}

          <div className={styles.cards}>
            <section className={styles.card}>
              <header className={styles.cardHeader}>
                <span className={styles.cardTitle}>Server</span>
                <span className={styles.cardNote}>{server.platform}</span>
              </header>
              <dl className={styles.specs}>
                <Spec label="CPU" value={`${server.cpu_cores} cores`} />
                <Spec
                  label="Load"
                  value={`${server.load_per_core.toFixed(2)} per core`}
                  warn={server.load_per_core > 1}
                  note={server.load_per_core > 1 ? 'work is queuing for a core' : 'idle enough'}
                />
                <Spec
                  label="Memory"
                  value={`${(server.memory_available_mb / 1024).toFixed(1)} of ${(
                    server.memory_total_mb / 1024
                  ).toFixed(1)} GB free`}
                />
                <Spec
                  label="Disk"
                  value={`${server.disk_free_gb} of ${server.disk_total_gb} GB free`}
                />
                <Spec
                  label="GPU"
                  value={server.gpu ?? 'none'}
                  note={server.gpu ? '' : 'GPU work will not be faster here'}
                />
              </dl>
            </section>

            <section className={styles.card}>
              <header className={styles.cardHeader}>
                <input
                  className={styles.deviceName}
                  value={settings.device_label}
                  onChange={(event) => {
                    setSettings({ ...settings, device_label: event.target.value });
                  }}
                  onBlur={(event) => {
                    void save({ device_label: event.target.value });
                  }}
                />
                <span className={styles.cardNote}>as the browser reports it</span>
              </header>
              <dl className={styles.specs}>
                <Spec label="CPU" value={local.cores ? `${local.cores} cores` : 'not reported'} />
                <Spec
                  label="Memory"
                  value={local.memory_gb ? `${local.memory_gb} GB` : 'not reported'}
                  note="rounded to a power of two by the browser"
                />
                <Spec label="WebGPU" value={local.webgpu ? 'available' : 'not available'} />
                <Spec
                  label="Shared memory"
                  value={local.shared_memory ? 'available' : 'not available'}
                  note={
                    local.shared_memory
                      ? 'workers can share buffers'
                      : 'workers must copy every buffer'
                  }
                />
                <Spec label="Workers" value={`${workers} at the current share`} />
              </dl>

              <p className={styles.caution}>
                <Icon name="warning" size={12} /> Every figure here is what the browser chooses to
                report. Core counts are capped and memory is rounded, both deliberately, so treat
                them as hints rather than as this machine&rsquo;s specification.
              </p>
            </section>
          </div>

          <section className={styles.panel}>
            <header className={styles.panelHeader}>
              <span className={styles.panelTitle}>Where each feature runs</span>
              <span className={styles.panelNote}>auto picks whichever is less busy</span>
            </header>
            <div className={styles.routing}>
              {FEATURES.map((feature) => {
                const lockedReason = settings.locked[feature.key];
                return (
                  <div key={feature.key} className={styles.routeRow}>
                    <span className={styles.routeLabel}>
                      {feature.label}
                      <span className={styles.routeNote}>{feature.note}</span>
                    </span>

                    <span className={styles.segmented}>
                      {SOURCES.map((source) => (
                        <button
                          key={source.key}
                          type="button"
                          disabled={busy || lockedReason !== undefined}
                          className={`${styles.segment} ${
                            settings.routing[feature.key] === source.key ? styles.segmentOn : ''
                          }`}
                          onClick={() => {
                            void save({ routing: { [feature.key]: source.key } });
                          }}
                        >
                          {source.label}
                        </button>
                      ))}
                    </span>

                    {lockedReason !== undefined ? (
                      <span className={styles.lock} title={lockedReason}>
                        <Icon name="lock" size={12} />
                        {lockedReason}
                      </span>
                    ) : (
                      <span />
                    )}
                  </div>
                );
              })}
            </div>
          </section>

          <section className={styles.panel}>
            <header className={styles.panelHeader}>
              <span className={styles.panelTitle}>What a browser job may use</span>
              <span className={styles.panelNote}>one core is always left free</span>
            </header>
            <div className={styles.sliders}>
              <Slider
                label="CPU workers"
                value={settings.cpu_share_percent}
                suffix={`% · ${workers} worker${workers === 1 ? '' : 's'}`}
                onCommit={(value) => void save({ cpu_share_percent: value })}
              />
              <Slider
                label="GPU duty cycle"
                value={settings.gpu_duty_percent}
                suffix={local.webgpu ? '%' : '% · no WebGPU here'}
                disabled={!local.webgpu}
                onCommit={(value) => void save({ gpu_duty_percent: value })}
              />
              <Slider
                label="Memory budget"
                value={Math.round((settings.ram_budget_mb / 1024) * 10) / 10}
                min={0.5}
                max={16}
                step={0.5}
                suffix=" GB"
                onCommit={(value) => void save({ ram_budget_mb: Math.round(value * 1024) })}
              />
            </div>
          </section>

          <section className={styles.panel}>
            <header className={styles.panelHeader}>
              <span className={styles.panelTitle}>Jobs</span>
              <span className={styles.panelNote}>kept across restarts</span>
            </header>
            {jobs.length === 0 ? (
              <p className={styles.placeholder}>Nothing has run yet.</p>
            ) : (
              <div className={styles.tableScroll}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Job</th>
                      <th>Where</th>
                      <th>State</th>
                      <th>Progress</th>
                      <th>Started</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((job) => (
                      <tr key={job.id}>
                        <td>{job.label}</td>
                        <td>{job.source}</td>
                        <td>
                          <span className={styles[`state_${job.state}`] ?? ''}>{job.state}</span>
                          {job.state === 'interrupted' ? (
                            <span className={styles.routeNote}>a restart cut this short</span>
                          ) : null}
                        </td>
                        <td className="num">
                          {job.total > 0 ? `${Math.round((job.done / job.total) * 100)}%` : '—'}
                        </td>
                        <td className="num">{new Date(job.created_at).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}

function Spec({
  label,
  value,
  note,
  warn,
}: {
  label: string;
  value: string;
  note?: string;
  warn?: boolean;
}) {
  return (
    <div className={styles.spec}>
      <dt>{label}</dt>
      <dd className={warn ? styles.warn : ''}>
        {value}
        {note ? <span className={styles.routeNote}>{note}</span> : null}
      </dd>
    </div>
  );
}

function Slider({
  label,
  value,
  suffix,
  min = 0,
  max = 100,
  step = 5,
  disabled,
  onCommit,
}: {
  label: string;
  value: number;
  suffix: string;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  onCommit: (value: number) => void;
}) {
  const [local, setLocal] = useState(value);
  useEffect(() => {
    setLocal(value);
  }, [value]);

  return (
    <label className={styles.slider}>
      <span className={styles.sliderLabel}>
        {label}
        <span className={styles.sliderValue}>
          {local}
          {suffix}
        </span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={local}
        disabled={disabled}
        onChange={(event) => {
          setLocal(Number(event.target.value));
        }}
        // Committed on release, not on every pixel: each change is a
        // request, and a drag would send dozens.
        onPointerUp={() => {
          onCommit(local);
        }}
        onKeyUp={() => {
          onCommit(local);
        }}
      />
    </label>
  );
}
