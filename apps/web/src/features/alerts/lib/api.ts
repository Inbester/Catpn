/** Typed calls for alerts, channels and paper trading. */

import { api } from '@/lib/api/client';
import type { Alert, AlertEvent, Channel, Destination, PaperSession } from './types';

export interface AlertPayload {
  name: string;
  source: Alert['source'];
  setup_id?: string | null;
  symbol: string;
  interval?: string;
  condition?: Record<string, unknown>;
  trigger_mode?: Alert['trigger_mode'];
  repeat_mode?: Alert['repeat_mode'];
  expires_at?: string | null;
  quiet_from_hour?: number | null;
  quiet_to_hour?: number | null;
  template?: string;
  locale?: 'en' | 'fa';
  destinations?: Destination[];
  enabled?: boolean;
}

export const listAlerts = (enabledOnly = false) =>
  api.get<Alert[]>(`/alerts?enabled_only=${enabledOnly ? 'true' : 'false'}`);

export const createAlert = (payload: AlertPayload) => api.post<Alert>('/alerts', payload);

export const updateAlert = (id: string, payload: AlertPayload) =>
  api.put<Alert>(`/alerts/${id}`, payload);

export const deleteAlert = (id: string) => api.delete<void>(`/alerts/${id}`);

export const listEvents = () => api.get<AlertEvent[]>('/alerts/events');

export const testSend = (id: string, message = '') =>
  api.post<AlertEvent>(`/alerts/${id}/test`, { message });

export interface Preview {
  message: string;
  unknown_variables: string[];
}

export const previewTemplate = (template: string, locale: 'en' | 'fa' = 'en') =>
  api.post<Preview>('/alerts/preview', { template, locale });

export const listChannels = () => api.get<Channel[]>('/channels');

export const listPaperSessions = () => api.get<PaperSession[]>('/paper');

export const promotePaper = (id: string, override = false) =>
  api.post<PaperSession>(`/paper/${id}/promote`, { override });
