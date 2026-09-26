/** Compute preferences and server specs (SPEC §3.6). */

import { api } from '@/lib/api/client';

export type ComputeFeature = 'chart_data' | 'research' | 'alerts' | 'ai' | 'bot';
export type ComputeSource = 'server' | 'local' | 'auto';

export interface ServerSpecs {
  platform: string;
  cpu_cores: number;
  load_per_core: number;
  memory_total_mb: number;
  memory_available_mb: number;
  disk_total_gb: number;
  disk_free_gb: number;
  gpu: string | null;
}

export interface LocalProfile {
  cores?: number;
  memory_gb?: number;
  webgpu?: boolean;
  shared_memory?: boolean;
  user_agent?: string;
}

export interface ComputeSettings {
  routing: Record<ComputeFeature, ComputeSource>;
  /** Features that may only run on the server, mapped to the reason. */
  locked: Partial<Record<ComputeFeature, string>>;
  cpu_share_percent: number;
  gpu_duty_percent: number;
  ram_budget_mb: number;
  local_profile: LocalProfile;
  device_label: string;
  server: ServerSpecs;
}

export interface ComputeUpdate {
  routing?: Partial<Record<ComputeFeature, ComputeSource>>;
  cpu_share_percent?: number;
  gpu_duty_percent?: number;
  ram_budget_mb?: number;
  device_label?: string;
  local_profile?: LocalProfile;
}

export const getCompute = () => api.get<ComputeSettings>('/compute');

export const updateCompute = (update: ComputeUpdate) =>
  api.put<ComputeSettings>('/compute', update);

export interface JobHistoryEntry {
  id: string;
  kind: string;
  label: string;
  state: string;
  source: string;
  done: number;
  total: number;
  created_at: string;
  finished_at: string | null;
  error: string | null;
  request: Record<string, unknown>;
}

export const jobHistory = () => api.get<JobHistoryEntry[]>('/jobs/history');
