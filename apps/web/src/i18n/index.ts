/**
 * i18n setup.
 *
 * The interface is English, and only English. Persian is not a second UI
 * language here — it is contextual help: hovering a term shows its Persian
 * translation and an explanation, which is what `features/glossary` does.
 * Keeping the chrome in one language and the help in another means the
 * layout never flips direction and nothing has to be kept in step.
 *
 * The framework stays because strings out of components is worth it on its
 * own, and because a second locale is then a bundle rather than a rewrite.
 */
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import en from './en.json';

export const SUPPORTED_LOCALES = ['en'] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

export function isSupportedLocale(value: string): value is Locale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
  },
  lng: 'en',
  fallbackLng: 'en',
  interpolation: {
    // React already escapes.
    escapeValue: false,
  },
  returnNull: false,
});

export function applyLocale(locale: Locale): void {
  void i18n.changeLanguage(locale);
  document.documentElement.lang = locale;
  // Always left to right. The Persian in the glossary tip marks itself
  // rtl on its own elements rather than turning the document around.
  document.documentElement.dir = 'ltr';
}

export default i18n;
