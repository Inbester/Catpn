/**
 * Authentication state.
 *
 * The access token lives in the API client's module scope, not here, so it is
 * never serialised into devtools snapshots or persisted state.
 */

import { create } from 'zustand';

import { api, refreshSession, setAccessToken, setCsrfToken } from '@/lib/api/client';
import type { Calendar, LoginResponse, Theme, TokenResponse, User } from '@/lib/api/types';
import { isMfaRequired } from '@/lib/api/types';

export type AuthStatus = 'unknown' | 'authenticated' | 'anonymous' | 'mfa-required';

interface AuthState {
  status: AuthStatus;
  user: User | null;
  /** Held between the password step and the TOTP step. */
  mfaTicket: string | null;

  bootstrap: () => Promise<void>;
  login: (email: string, password: string) => Promise<AuthStatus>;
  verifyMfa: (code: string) => Promise<void>;
  register: (email: string, displayName: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  updatePreferences: (changes: {
    theme?: Theme;
    locale?: string;
    calendar?: Calendar;
    timezone?: string;
  }) => Promise<void>;
  clearSession: () => void;
}

function applyTokens(response: TokenResponse): void {
  setAccessToken(response.access_token);
  setCsrfToken(response.csrf_token);
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: 'unknown',
  user: null,
  mfaTicket: null,

  /**
   * On load, recover the session from the refresh cookie.
   *
   * This deliberately goes through the client's deduplicated
   * `refreshSession`: React StrictMode mounts effects twice in development,
   * and two concurrent rotations would make the server reject one of them.
   */
  bootstrap: async () => {
    const result = await refreshSession();
    if (result) {
      set({
        status: 'authenticated',
        user: result.user as TokenResponse['user'],
        mfaTicket: null,
      });
    } else {
      set({ status: 'anonymous', user: null, mfaTicket: null });
    }
  },

  login: async (email, password) => {
    const response = await api.post<LoginResponse>(
      '/auth/login',
      { email, password },
      { skipRefresh: true },
    );

    if (isMfaRequired(response)) {
      set({ status: 'mfa-required', mfaTicket: response.ticket });
      return 'mfa-required';
    }

    applyTokens(response);
    set({ status: 'authenticated', user: response.user, mfaTicket: null });
    return 'authenticated';
  },

  verifyMfa: async (code) => {
    const ticket = get().mfaTicket;
    if (!ticket) throw new Error('This sign-in attempt expired. Please start again.');

    const response = await api.post<TokenResponse>(
      '/auth/login/mfa',
      { ticket, code },
      { skipRefresh: true },
    );
    applyTokens(response);
    set({ status: 'authenticated', user: response.user, mfaTicket: null });
  },

  register: async (email, displayName, password) => {
    await api.post<User>(
      '/auth/register',
      { email, display_name: displayName, password },
      { skipRefresh: true },
    );
    await get().login(email, password);
  },

  logout: async () => {
    try {
      await api.post('/auth/logout');
    } catch {
      // Signing out locally matters more than the server round trip.
    }
    get().clearSession();
  },

  updatePreferences: async (changes) => {
    const user = await api.patch<User>('/users/me/preferences', changes);
    set({ user });
  },

  clearSession: () => {
    setAccessToken(null);
    setCsrfToken(null);
    set({ status: 'anonymous', user: null, mfaTicket: null });
  },
}));
