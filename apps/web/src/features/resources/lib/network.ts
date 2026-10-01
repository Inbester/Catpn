/** WireGuard tunnels and feature routing (SPEC §3.6, §9). */

import { api } from '@/lib/api/client';

export interface TunnelSummary {
  endpoint: string;
  public_key: string;
  address: string[];
  dns: string[];
  allowed_ips: string[];
  keepalive: number | null;
  has_preshared_key: boolean;
}

/** What the server says the tunnel process is doing right now. */
export type TunnelState = 'running' | 'stopped' | 'failed' | 'off' | 'unavailable';

export interface TestResult {
  state?: 'ok' | 'failed' | 'unavailable' | 'off';
  detail?: string;
  quality?: 'good' | 'fair' | 'poor' | 'down' | null;
  latency_ms?: number | null;
  jitter_ms?: number | null;
  loss_percent?: number | null;
  exit_ip?: string | null;
}

export interface Tunnel {
  id: string;
  label: string;
  enabled: boolean;
  priority: number;
  summary: TunnelSummary;
  state: TunnelState;
  last_error: string | null;
  last_tested_at: string | null;
  last_result: TestResult;
  warnings?: string[];
}

export interface Engine {
  available: boolean;
  amnezia: boolean;
  detail: string;
}

export interface Features {
  routable: string[];
  locked: Record<string, string>;
}

export interface Validation {
  valid: boolean;
  errors: string[];
  warnings: string[];
  summary: TunnelSummary | null;
}

export const getEngine = () => api.get<Engine>('/network/engine');
export const listTunnels = () => api.get<Tunnel[]>('/network/tunnels');
export const getFeatures = () => api.get<Features>('/network/features');
export const getRoutes = () => api.get<Record<string, string[]>>('/network/routes');
export const validate = (config: string) => api.post<Validation>('/network/validate', { config });
export const importTunnel = (label: string, config: string) =>
  api.post<Tunnel>('/network/tunnels', { label, config });
export const updateTunnel = (
  id: string,
  changes: Partial<Pick<Tunnel, 'label' | 'enabled' | 'priority'>>,
) => api.patch<Tunnel>(`/network/tunnels/${id}`, changes);
export const testTunnel = (id: string) => api.post<TestResult>(`/network/tunnels/${id}/test`);
export const removeTunnel = (id: string) => api.delete(`/network/tunnels/${id}`);
export const setRoute = (feature: string, tunnelIds: string[]) =>
  api.put<Record<string, string[]>>('/network/routes', { feature, tunnel_ids: tunnelIds });

/**
 * The ordered list a primary and fallback choice make.
 *
 * Empty strings mean "none", and a fallback equal to the primary adds
 * nothing — the server refuses a tunnel listed twice, so it is dropped
 * here rather than turned into an error the user has to read.
 */
export function routeIds(primary: string, fallback: string): string[] {
  const ids = [primary, fallback].filter((id) => id !== '');
  return ids.filter((id, index) => ids.indexOf(id) === index);
}

/** One line for the last measurement, or why there is none. */
export function describeResult(result: TestResult): string {
  if (!result.state) return 'Never tested.';
  if (result.state !== 'ok') return result.detail || 'The test did not complete.';
  const parts = [
    result.exit_ip ? `exit ${result.exit_ip}` : null,
    result.latency_ms != null ? `${Math.round(result.latency_ms)} ms` : null,
    result.jitter_ms != null ? `±${Math.round(result.jitter_ms)} ms jitter` : null,
    result.loss_percent != null ? `${result.loss_percent}% loss` : null,
  ];
  return parts.filter(Boolean).join(' · ');
}

export const STATE_LABELS: Record<TunnelState, string> = {
  // Running is the process; whether traffic gets through is what Test says.
  running: 'Running',
  stopped: 'Idle',
  failed: 'Failed',
  off: 'Off',
  unavailable: 'Cannot run here',
};
