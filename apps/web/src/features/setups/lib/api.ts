/** Typed calls for the Setup routes. */

import { api } from '@/lib/api/client';
import type { Setup, SetupsOverview, Stage, StageStatus } from './types';

export const listSetups = (includeArchived = false) =>
  api.get<Setup[]>(`/setups?include_archived=${includeArchived ? 'true' : 'false'}`);

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
  use_in_backtest?: boolean;
  use_in_forward?: boolean;
  use_in_paper?: boolean;
  use_in_alerts?: boolean;
}

export const createSetup = (request: CreateSetupRequest) => api.post<Setup>('/setups', request);

export const advanceStage = (setupId: string, stage: Stage, status: StageStatus, note = '') =>
  api.post<Setup>(`/setups/${setupId}/stage`, { stage, status, note });

export const archiveSetup = (setupId: string) => api.delete<void>(`/setups/${setupId}`);
