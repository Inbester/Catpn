import { describe, expect, it } from 'vitest';

import en from './en.json';
import fa from './fa.json';
import { applyLocale, isRtl, isSupportedLocale, SUPPORTED_LOCALES } from './index';

/** Collect every leaf key path, e.g. "nav.chart". */
function keyPaths(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null) return [prefix];
  return Object.entries(value).flatMap(([key, child]) =>
    keyPaths(child, prefix ? `${prefix}.${key}` : key),
  );
}

describe('i18n bundles', () => {
  it('ships English and Persian', () => {
    expect(SUPPORTED_LOCALES).toEqual(['en', 'fa']);
  });

  it('keeps the Persian bundle in step with English', () => {
    // A missing key silently falls back to English at runtime, which is easy
    // to ship by accident; catching it here keeps the RTL pass honest.
    expect(keyPaths(fa).sort()).toEqual(keyPaths(en).sort());
  });

  it('marks Persian as RTL and English as LTR', () => {
    expect(isRtl('fa')).toBe(true);
    expect(isRtl('en')).toBe(false);
  });

  it('validates locale codes', () => {
    expect(isSupportedLocale('en')).toBe(true);
    expect(isSupportedLocale('fa')).toBe(true);
    expect(isSupportedLocale('de')).toBe(false);
  });

  it('sets document lang and dir when switching', () => {
    applyLocale('fa');
    expect(document.documentElement.lang).toBe('fa');
    expect(document.documentElement.dir).toBe('rtl');

    applyLocale('en');
    expect(document.documentElement.lang).toBe('en');
    expect(document.documentElement.dir).toBe('ltr');
  });
});
