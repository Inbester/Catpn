import { beforeEach, describe, expect, it, vi } from 'vitest';

import { applyTheme, DEFAULT_THEME, initTheme, isTheme, readStoredTheme } from './theme';

describe('theme', () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset['theme'];
  });

  it('defaults to Graphite, the approved default (SPEC D2)', () => {
    expect(DEFAULT_THEME).toBe('graphite');
    expect(initTheme()).toBe('graphite');
    expect(document.documentElement.dataset['theme']).toBe('graphite');
  });

  it('applies a theme to the document element', () => {
    applyTheme('paper');
    expect(document.documentElement.dataset['theme']).toBe('paper');
  });

  it('persists and restores the choice', () => {
    applyTheme('paper');
    expect(readStoredTheme()).toBe('paper');
    expect(initTheme()).toBe('paper');
  });

  it('ignores a corrupted stored value', () => {
    localStorage.setItem('quanta.theme', 'neon');
    expect(readStoredTheme()).toBeNull();
    expect(initTheme()).toBe('graphite');
  });

  it('still applies the theme when storage throws', () => {
    // Private browsing and blocked site data both make setItem throw.
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(() => {
      applyTheme('paper');
    }).not.toThrow();
    expect(document.documentElement.dataset['theme']).toBe('paper');
    spy.mockRestore();
  });

  it('recognises only the two approved themes', () => {
    expect(isTheme('graphite')).toBe(true);
    expect(isTheme('paper')).toBe(true);
    expect(isTheme('midnight')).toBe(false);
    expect(isTheme(null)).toBe(false);
  });
});
