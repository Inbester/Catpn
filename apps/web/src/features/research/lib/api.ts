/** Typed calls for the research studies and the job runner. */

import { api } from '@/lib/api/client';
import type { BacktestConfig } from '@/features/test/lib/types';
import type {
  DiscoverPlan,
  LeverageStudy,
  RobustnessStudy,
  ServerJob,
  TradeRiskStudy,
} from './types';
import type { IndicatorChoice, IndicatorSpec } from './indicators';

export interface Range {
  symbol: string;
  interval: string;
  start?: number | null;
  end?: number | null;
}

export const listIndicators = () => api.get<IndicatorSpec[]>('/research/indicators');

export const leverageStudy = (
  strategyId: string,
  request: Range & {
    margins: number[];
    leverages: number[];
    budget_percent?: number | null;
    config: BacktestConfig;
  },
) => api.post<LeverageStudy>(`/research/${strategyId}/leverage`, request);

export const tradeRiskStudy = (strategyId: string, request: Range & { config: BacktestConfig }) =>
  api.post<TradeRiskStudy>(`/research/${strategyId}/trade-risk`, request);

export const robustnessStudy = (
  strategyId: string,
  request: Range & { grid: Record<string, number[]>; config: BacktestConfig },
) => api.post<RobustnessStudy>(`/research/${strategyId}/robustness`, request);

export interface DiscoverChoice {
  indicators: IndicatorChoice[];
  mix_indicators: boolean;
  require: string[];
  max_conditions: number;
}

export const discoverPlan = (request: Range & DiscoverChoice) =>
  api.post<DiscoverPlan>('/research/discover/plan', request);

export const startDiscover = (
  request: Range & DiscoverChoice & { cost_percent: number; max_hits?: number },
) => api.post<ServerJob>('/research/discover', request);

export const listJobs = () => api.get<ServerJob[]>('/jobs');

export const getJob = (jobId: string) => api.get<ServerJob>(`/jobs/${jobId}`);

export const cancelJob = (jobId: string) => api.delete<{ cancelled: boolean }>(`/jobs/${jobId}`);
