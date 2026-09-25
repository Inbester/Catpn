import { describe, expect, it } from 'vitest';

import { selectQueuedCount, selectRingProgress, useJobsStore, type Job } from './jobsStore';

const job = (overrides: Partial<Job>): Job => ({
  id: 'j',
  title: 'Job',
  state: 'running',
  progress: 0,
  ...overrides,
});

describe('jobs selectors', () => {
  it('is zero with no running jobs', () => {
    expect(selectRingProgress([])).toBe(0);
    expect(selectRingProgress([job({ state: 'queued', progress: 90 })])).toBe(0);
  });

  it('averages progress across running jobs', () => {
    expect(
      selectRingProgress([job({ id: 'a', progress: 40 }), job({ id: 'b', progress: 80 })]),
    ).toBe(60);
  });

  it('ignores non-running jobs when averaging', () => {
    expect(
      selectRingProgress([
        job({ id: 'a', progress: 50 }),
        job({ id: 'b', state: 'finished', progress: 100 }),
      ]),
    ).toBe(50);
  });

  it('counts only queued jobs', () => {
    expect(
      selectQueuedCount([
        job({ id: 'a', state: 'queued' }),
        job({ id: 'b', state: 'queued' }),
        job({ id: 'c', state: 'paused' }),
      ]),
    ).toBe(2);
  });
});

describe('jobs store', () => {
  it('upserts by id rather than duplicating', () => {
    useJobsStore.setState({ jobs: [] });
    const { upsertJob } = useJobsStore.getState();

    upsertJob(job({ id: 'a', progress: 10 }));
    upsertJob(job({ id: 'a', progress: 55 }));

    const { jobs } = useJobsStore.getState();
    expect(jobs).toHaveLength(1);
    expect(jobs[0]?.progress).toBe(55);
  });
});
