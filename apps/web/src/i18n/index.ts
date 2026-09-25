/**
 * i18n setup.
 *
 * SPEC D11: the UI ships in English with an i18n-ready frontend; Persian
 * (RTL chrome, LTR charts and numbers) follows later. The Persian bundle is
 * already here so strings are exercised in both directions from day one.
 */
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import en from './en.json';
import fa from './fa.json';

export const SUPPORTED_LOCALES = ['en', 'fa'] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

/** Persian is the only RTL locale so far. */
export const RTL_LOCALES: readonly Locale[] = ['fa'];

export function isRtl(locale: Locale): boolean {
  return RTL_LOCALES.includes(locale);
}

export function isSupportedLocale(value: string): value is Locale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    fa: { translation: fa },
  },
  lng: 'en',
  fallbackLng: 'en',
  interpolation: {
    // React already escapes.
    escapeValue: false,
  },
  returnNull: false,
});

/**
 * Switch language and update the document direction.
 *
 * Charts and numbers stay LTR even in Persian, so direction is set on the
 * document element and overridden locally rather than inherited everywhere.
 */
export function applyLocale(locale: Locale): void {
  void i18n.changeLanguage(locale);
  document.documentElement.lang = locale;
  document.documentElement.dir = isRtl(locale) ? 'rtl' : 'ltr';
}

export default i18n;
