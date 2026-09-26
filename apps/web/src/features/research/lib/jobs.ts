/**
 * Bridging server jobs into the rail's Jobs ring (SPEC D8).
 *
 * The ring was built in phase 0 with nothing to show. This is what fills
 * it: one poll for every job this user has, shared by every page, so
 * switching menus never loses a running search.
 *
 * Polling rather than a socket, deliberately. A search reports progress a
 * thousand rules at a time and finishes in under a minute; a second-by-
 * second poll costs one small request and cannot get stuck half-open the
 * way a socket can. The interval backs off to nothing when no job is
 * running, so an idle session makes no requests at all.
 */

import { useJobsStore, type Job } from '@/components/shell/jobsStore';
import * as researchApi from './api';
import type { ServerJob } from './types';

const ACTIVE_INTERVAL_MS = 1_000;
const IDLE_INTERVAL_MS = 15_000;

function toRailJob(job: ServerJob): Job {
  return {
    id: job.id,
    title: job.label,
    state:
      job.state === 'running'
        ? 'running'
        : job.state === 'queued'
          ? 'queued'
          : job.state === 'cancelled'
            ? 'paused'
            : 'finished',
    progress: Math.round(job.percent),
  };
}

let timer: ReturnType<typeof setTimeout> | null = null;
let listeners = 0;
let latest: ServerJob[] = [];
const subscribers = new Set<(jobs: ServerJob[]) => void>();

async function tick(): Promise<void> {
  try {
    latest = await researchApi.listJobs();
    useJobsStore.getState().setJobs(latest.map(toRailJob));
    for (const notify of subscribers) notify(latest);
  } catch {
    // A failed poll is not worth surfacing: the next one will either
    // work or the session has ended, which the API client handles.
  }

  if (listeners === 0) return;
  const active = latest.some((job) => job.state === 'running' || job.state === 'queued');
  timer = setTimeout(() => void tick(), active ? ACTIVE_INTERVAL_MS : IDLE_INTERVAL_MS);
}

/** Start polling. Returns a stop function; polling ends at the last one. */
export function watchJobs(onJobs?: (jobs: ServerJob[]) => void): () => void {
  if (onJobs) subscribers.add(onJobs);
  listeners += 1;
  if (timer === null) void tick();

  return () => {
    if (onJobs) subscribers.delete(onJobs);
    listeners = Math.max(0, listeners - 1);
    if (listeners === 0 && timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  };
}

/** Poll one job until it stops running, then hand back its final state. */
export async function waitForJob(
  jobId: string,
  onProgress?: (job: ServerJob) => void,
  intervalMs = ACTIVE_INTERVAL_MS,
): Promise<ServerJob> {
  for (;;) {
    const job = await researchApi.getJob(jobId);
    onProgress?.(job);
    if (job.state !== 'running' && job.state !== 'queued') return job;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
