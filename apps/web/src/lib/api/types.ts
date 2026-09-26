/** Response shapes mirroring quanta/schemas on the API side. */

export type Theme = 'graphite' | 'paper';

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_verified: boolean;
  totp_enabled: boolean;
  theme: Theme;
  locale: string;
  timezone: string;
  created_at: string;
  last_login_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  csrf_token: string;
  user: User;
}

export interface MfaRequiredResponse {
  mfa_required: true;
  ticket: string;
  expires_in: number;
}

export type LoginResponse = TokenResponse | MfaRequiredResponse;

export function isMfaRequired(response: LoginResponse): response is MfaRequiredResponse {
  return 'mfa_required' in response;
}

export type DocumentKind = 'chart' | 'strategy' | 'research' | 'settings' | 'layout' | 'ui';

export interface WorkspaceDocument<T = Record<string, unknown>> {
  id: string;
  kind: DocumentKind;
  scope_key: string;
  data: T;
  revision: number;
  device_label: string | null;
  updated_at: string;
}

export interface WorkspaceRevision {
  id: string;
  revision: number;
  label: string | null;
  summary: string | null;
  device_label: string | null;
  created_at: string;
}
