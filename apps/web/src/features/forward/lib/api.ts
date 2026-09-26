/** Typed calls for the forward-test routes. Setups live in features/setups. */

import { api } from '@/lib/api/client';
import type { BacktestConfig } from '@/features/test/lib/types';
import type { Period } from './presets';
import type { ComparisonResult, WalkForwardResult } from './types';

export interface ComparisonRequest {
  symbol: string;
  interval: string;
  reference: Period;
  test: Period;
  config: BacktestConfig;
  monte_carlo_runs?: number;
}

export const comparePeriods = (strategyId: string, request: ComparisonRequest) =>
  api.post<ComparisonResult>(`/forward/${strategyId}/periods`, request);

export interface WalkForwardRequest {
  symbol: string;
  interval: string;
  in_sample_days: number;
  out_of_sample_days: number;
  max_windows: number;
  grid: Record<string, number[]>;
  config: BacktestConfig;
}

export const runWalkForward = (strategyId: string, request: WalkForwardRequest) =>
  api.post<WalkForwardResult>(`/forward/${strategyId}/walk-forward`, request);
