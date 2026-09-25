/**
 * Theme handling.
 *
 * Theme A "Graphite" is the default, theme B "Paper" the alternative
 * (SPEC D2). The choice is applied to `<html data-theme>` before React
 * mounts, so there is no flash of the wrong theme on load, and is synced to
 * the account once signed in.
 */

import type { Theme } from '@/lib/api/types';

const STORAGE_KEY = 'quanta.theme';
export const DEFAULT_THEME: Theme = 'graphite';

export function isTheme(value: unknown): value is Theme {
  return value === 'graphite' || value === 'paper';
}

export function readStoredTheme(): Theme | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return isTheme(stored) ? stored : null;
  } catch {
    // Private mode or blocked storage — fall back to the default.
    return null;
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset['theme'] = theme;
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Not fatal: the theme is still applied for this session.
  }
}

/** Run before React mounts to avoid a flash of the wrong theme. */
export function initTheme(): Theme {
  const theme = readStoredTheme() ?? DEFAULT_THEME;
  applyTheme(theme);
  return theme;
}
