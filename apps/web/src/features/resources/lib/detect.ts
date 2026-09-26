/**
 * What this browser can tell us about the machine it is on.
 *
 * Every figure here is a hint, not a measurement. `hardwareConcurrency`
 * is capped by the browser for fingerprinting reasons, `deviceMemory` is
 * rounded to a power of two and only exists on Chromium, and WebGPU
 * adapter details are deliberately vague. So the page presents them as
 * "what the browser reports" and never as the machine's specification —
 * promising otherwise would make a capacity slider lie.
 */

import type { LocalProfile } from './api';

export async function detectLocal(): Promise<LocalProfile> {
  const profile: LocalProfile = {
    user_agent: navigator.userAgent.slice(0, 200),
    // Cross-origin isolation, which SharedArrayBuffer needs. Without it a
    // worker pool cannot share memory and has to copy every buffer.
    shared_memory: typeof crossOriginIsolated === 'boolean' ? crossOriginIsolated : false,
  };

  if (navigator.hardwareConcurrency) profile.cores = navigator.hardwareConcurrency;

  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
  if (typeof memory === 'number') profile.memory_gb = memory;

  try {
    const gpu = (navigator as Navigator & { gpu?: { requestAdapter: () => Promise<unknown> } }).gpu;
    profile.webgpu = gpu ? (await gpu.requestAdapter()) !== null : false;
  } catch {
    profile.webgpu = false;
  }

  return profile;
}

/** How many workers to start, given the share the user allowed. */
export function workerCount(cores: number | undefined, sharePercent: number): number {
  if (!cores || cores < 2) return 1;
  // One core is always left alone: a machine whose every core is busy
  // cannot redraw the page that is showing the progress.
  const usable = cores - 1;
  return Math.max(1, Math.min(usable, Math.round((usable * sharePercent) / 100)));
}
