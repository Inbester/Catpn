/** Typed calls for the forward-test and Setup routes. */

import { api } from '@/lib/api/client';
import type { BacktestConfig } from '@/features/test/lib/types';
import type { Period } from './presets';
import type { ComparisonResult, Setup, SetupsOverview, WalkForwardResult } from './types';

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

export const listSetups = () => api.get<Setup[]>('/setups');

export const setupsOverview = () => api.get<SetupsOverview>('/setups/overview');

export interface CreateSetupRequest {
  name: string;
  color: string;
  strategy_id: string;
  symbol: string;
  interval: string;
  margin_percent: number;
  leverage: number;
  margin_mode: 'isolated' | 'cross';
  fee_tier?: string;
  maker_fee?: number;
  taker_fee?: number;
  max_drawdown_budget_percent?: number | null;
  source_run_id?: string | null;
}

export const createSetup = (request: CreateSetupRequest) => api.post<Setup>('/setups', request);

export const advanceStage = (setupId: string, stage: string, status: string, note = '') =>
  api.post<Setup>(`/setups/${setupId}/stage`, { stage, status, note });
