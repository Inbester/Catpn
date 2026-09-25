/**
 * API client.
 *
 * Access tokens live in memory only — never localStorage, where any XSS could
 * read them. The refresh token is an HttpOnly cookie the browser sends on its
 * own, so a reload recovers the session by calling `/auth/refresh`.
 */

export const API_PREFIX = '/api/v1';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

let accessToken: string | null = null;
let csrfToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Read the CSRF cookie, which is deliberately not HttpOnly. */
function readCsrfCookie(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)quanta_csrf=([^;]*)/);
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

/** Listeners notified when the session ends and the user must sign in again. */
type SessionExpiredListener = () => void;
const sessionExpiredListeners = new Set<SessionExpiredListener>();

export function onSessionExpired(listener: SessionExpiredListener): () => void {
  sessionExpiredListeners.add(listener);
  return () => {
    sessionExpiredListeners.delete(listener);
  };
}

function notifySessionExpired(): void {
  for (const listener of sessionExpiredListeners) listener();
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  /** Set for the refresh call itself, to stop it recursing. */
  skipRefresh?: boolean;
}

/**
 * Refresh deduplication.
 *
 * Several requests can 401 at once when a token expires; without this they
 * would each rotate the refresh cookie, and all but the winner would be
 * rejected as replays.
 */
export interface RefreshResult {
  access_token: string;
  csrf_token: string;
  user: unknown;
}

let refreshInFlight: Promise<RefreshResult | null> | null = null;

/**
 * Rotate the session, at most once at a time.
 *
 * Every caller — the startup bootstrap, a 401 retry, several requests
 * expiring together — goes through this one promise. Firing two refreshes
 * concurrently would rotate the cookie twice, and the server treats a token
 * that has already been rotated as a possible replay.
 */
export async function refreshSession(): Promise<RefreshResult | null> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${API_PREFIX}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!response.ok) return null;

      const data = (await response.json()) as RefreshResult;
      accessToken = data.access_token;
      csrfToken = data.csrf_token;
      return data;
    } catch {
      return null;
    } finally {
      // Cleared on the next tick so concurrent callers all see this result.
      queueMicrotask(() => {
        refreshInFlight = null;
      });
    }
  })();

  return refreshInFlight;
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const contentType = response.headers.get('Content-Type') ?? '';
  if (!contentType.includes('application/json')) return response.text();
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function errorMessage(body: unknown, fallback: string): string {
  if (typeof body === 'object' && body !== null && 'detail' in body) {
    const detail = body.detail;
    if (typeof detail === 'string') return detail;
    // FastAPI validation errors arrive as a list of {loc, msg}.
    if (Array.isArray(detail)) {
      const first: unknown = detail[0];
      if (typeof first === 'object' && first !== null && 'msg' in first) {
        const msg = first.msg;
        if (typeof msg === 'string') return msg;
      }
    }
  }
  return fallback;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, skipRefresh = false, headers, ...rest } = options;

  const send = async (): Promise<Response> => {
    const finalHeaders = new Headers(headers);
    if (body !== undefined) finalHeaders.set('Content-Type', 'application/json');
    if (accessToken) finalHeaders.set('Authorization', `Bearer ${accessToken}`);

    const method = (rest.method ?? 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD') {
      const token = csrfToken ?? readCsrfCookie();
      if (token) finalHeaders.set('X-CSRF-Token', token);
    }

    return fetch(`${API_PREFIX}${path}`, {
      ...rest,
      headers: finalHeaders,
      credentials: 'include',
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  };

  let response = await send();

  // One transparent retry after refreshing an expired access token.
  if (response.status === 401 && !skipRefresh) {
    if (await refreshSession()) {
      response = await send();
    } else {
      accessToken = null;
      notifySessionExpired();
    }
  }

  const parsed = await parseBody(response);
  if (!response.ok) {
    throw new ApiError(response.status, errorMessage(parsed, response.statusText), parsed);
  }
  return parsed as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: 'DELETE' }),
};
