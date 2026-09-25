/** Typed calls for the strategy and backtest routes. */

import { api } from '@/lib/api/client';
import type {
  BacktestConfig,
  BacktestRun,
  BacktestSummary,
  FunctionReference,
  Strategy,
  StrategyPayload,
  ValidationResult,
} from './types';

export const listStrategies = () => api.get<Strategy[]>('/strategies');

export const createStrategy = (payload: StrategyPayload) =>
  api.post<Strategy>('/strategies', payload);

export const updateStrategy = (id: string, payload: StrategyPayload) =>
  api.put<Strategy>(`/strategies/${id}`, payload);

export const deleteStrategy = (id: string) => api.delete<null>(`/strategies/${id}`);

export const validateStrategy = (payload: StrategyPayload) =>
  api.post<ValidationResult>('/strategies/validate', payload);

export const listFunctions = () => api.get<FunctionReference[]>('/strategies/functions');

export interface RunRequest {
  symbol: string;
  interval: string;
  start?: number;
  end?: number;
  config: BacktestConfig;
}

export const runBacktest = (strategyId: string, request: RunRequest) =>
  api.post<BacktestRun>(`/strategies/${strategyId}/backtest`, request);

export const listRuns = (strategyId: string) =>
  api.get<BacktestSummary[]>(`/strategies/${strategyId}/backtests`);

export const getRun = (runId: string) => api.get<BacktestRun>(`/backtests/${runId}`);

/** The CSV export URL. Downloaded through a normal link, not fetch. */
export const tradesCsvPath = (runId: string) => `/api/v1/backtests/${runId}/trades.csv`;
