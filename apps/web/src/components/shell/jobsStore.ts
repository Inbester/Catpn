/**
 * Global jobs state.
 *
 * SPEC §2 / DECISIONS: jobs live outside page components so switching menus
 * never stops them. Phase 4 populates this from the worker pool and the
 * server job runner; phase 0 ships the store and the rail chrome.
 */

import { create } from 'zustand';

export type JobState = 'running' | 'queued' | 'paused' | 'finished';

export interface Job {
  id: string;
  title: string;
  state: JobState;
  /** 0–100, only meaningful while running. */
  progress: number;
}

interface JobsState {
  jobs: Job[];
  setJobs: (jobs: Job[]) => void;
  upsertJob: (job: Job) => void;
}

export const useJobsStore = create<JobsState>((set) => ({
  jobs: [],
  setJobs: (jobs) => {
    set({ jobs });
  },
  upsertJob: (job) => {
    set((state) => {
      const index = state.jobs.findIndex((entry) => entry.id === job.id);
      if (index === -1) return { jobs: [...state.jobs, job] };
      const jobs = [...state.jobs];
      jobs[index] = job;
      return { jobs };
    });
  },
}));

/** Mean progress across running jobs; 0 when nothing is running. */
export function selectRingProgress(jobs: Job[]): number {
  const running = jobs.filter((job) => job.state === 'running');
  if (running.length === 0) return 0;
  const total = running.reduce((sum, job) => sum + job.progress, 0);
  return Math.round(total / running.length);
}

export function selectQueuedCount(jobs: Job[]): number {
  return jobs.filter((job) => job.state === 'queued').length;
}
