/** Settings endpoints (SPEC §3.6). */

import { request } from '@/lib/api/client';

export interface TotpStart {
  secret: string;
  provisioning_uri: string;
  qr_svg: string;
}

export interface TotpConfirmed {
  recovery_codes: string[];
}

export interface SessionRow {
  id: string;
  device_label: string | null;
  user_agent: string | null;
  created_at: string;
  last_used_at: string;
  expires_at: string;
}

export interface ExchangeKey {
  id: string;
  exchange: string;
  label: string;
  last_four: string;
  fingerprint: string;
  can_trade: boolean;
  ip_whitelist: string[];
  verified_at: string | null;
  last_used_at: string | null;
  created_at: string | null;
}

export interface ExchangeKeyList {
  /** Shown above the form: a key pasted before this is whitelisted is
   *  refused for a reason the user cannot see. */
  server_ip: string;
  keys: ExchangeKey[];
}

export const startTotp = () => request<TotpStart>('/auth/totp/start', { method: 'POST' });

export const confirmTotp = (code: string) =>
  request<TotpConfirmed>('/auth/totp/confirm', { method: 'POST', body: { code } });

export const disableTotp = (password: string, code: string) =>
  request<void>('/auth/totp/disable', { method: 'POST', body: { password, code } });

export const listSessions = () => request<SessionRow[]>('/auth/sessions');

export const revokeOtherSessions = () =>
  request<void>('/auth/sessions/revoke-all', { method: 'POST' });

export const listKeys = () => request<ExchangeKeyList>('/exchange-keys');

export const addKey = (body: {
  label: string;
  api_key: string;
  api_secret: string;
  exchange?: string;
}) =>
  request<ExchangeKey>('/exchange-keys', {
    method: 'POST',
    body: { exchange: 'bitunix', ...body },
  });

export const deleteKey = (id: string) =>
  request<void>(`/exchange-keys/${id}`, { method: 'DELETE' });
