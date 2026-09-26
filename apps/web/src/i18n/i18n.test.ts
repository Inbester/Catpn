import { describe, expect, it } from 'vitest';

import en from './en.json';
import { applyLocale, isSupportedLocale, SUPPORTED_LOCALES } from './index';

/** Collect every leaf key path, e.g. "nav.chart". */
function keyPaths(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null) return [prefix];
  return Object.entries(value).flatMap(([key, child]) =>
    keyPaths(child, prefix ? `${prefix}.${key}` : key),
  );
}

describe('i18n bundles', () => {
  it('ships English only', () => {
    // Persian is contextual help on hover, not a second interface
    // language: see features/glossary.
    expect(SUPPORTED_LOCALES).toEqual(['en']);
  });

  it('has no untranslated-looking keys', () => {
    expect(keyPaths(en).length).toBeGreaterThan(0);
  });

  it('validates locale codes', () => {
    expect(isSupportedLocale('en')).toBe(true);
    // A stored preference from before the interface was fixed to English
    // must not be applied.
    expect(isSupportedLocale('fa')).toBe(false);
    expect(isSupportedLocale('de')).toBe(false);
  });

  it('sets document lang and dir', () => {
    applyLocale('en');
    expect(document.documentElement.lang).toBe('en');
    expect(document.documentElement.dir).toBe('ltr');
  });
});
