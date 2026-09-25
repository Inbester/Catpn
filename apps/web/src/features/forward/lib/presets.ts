/**
 * Jalali period presets (SPEC §3.3).
 *
 * Presets resolve to explicit UTC ranges here, in the browser, because the
 * tested Jalali implementation already lives on this side. Sending epoch
 * milliseconds to the API keeps one calendar implementation instead of two
 * that could drift — the same reasoning that pins the chart's indicators to
 * the engine's.
 */

import {
  dateToJalali,
  jalaliMonthName,
  jalaliMonthRange,
  type JalaliDate,
} from '@/lib/date/jalali';

export interface Period {
  label: string;
  start: number;
  end: number;
}

export type PresetKey = 'same_month_last_year' | 'previous_month' | 'same_month_each_year';

export interface PresetOption {
  key: PresetKey;
  label: string;
  description: string;
}

export const PRESETS: readonly PresetOption[] = [
  {
    key: 'same_month_last_year',
    label: 'Same month · this year',
    description: 'This Jalali month against the same month last year.',
  },
  {
    key: 'previous_month',
    label: 'Previous month',
    description: 'The month just finished against the one before it.',
  },
  {
    key: 'same_month_each_year',
    label: 'Same month · every year',
    description: 'One pair per year, oldest against newest.',
  },
];

/** A readable label, e.g. "Farvardin 1404". */
export function monthLabel(jy: number, jm: number, locale: 'en' | 'fa' = 'en'): string {
  return `${jalaliMonthName(jm, locale)} ${jy}`;
}

function period(jy: number, jm: number, locale: 'en' | 'fa' = 'en'): Period {
  const { start, end } = jalaliMonthRange(jy, jm);
  return { label: monthLabel(jy, jm, locale), start: start.getTime(), end: end.getTime() };
}

/** The Jalali month a moment falls in. */
export function currentJalaliMonth(at: Date = new Date()): JalaliDate {
  return dateToJalali(at);
}

/** Step back one Jalali month, rolling the year at Farvardin. */
export function previousMonth(jy: number, jm: number): { jy: number; jm: number } {
  return jm === 1 ? { jy: jy - 1, jm: 12 } : { jy, jm: jm - 1 };
}

export interface JalaliMonth {
  jy: number;
  jm: number;
}

/**
 * The Jalali months a preset picks out.
 *
 * The *reference* is always the older month and the *test* the newer one:
 * a forward test asks whether what held before still holds now, so running
 * it the other way round would answer nothing.
 */
export function presetMonths(
  key: PresetKey,
  at: Date = new Date(),
): { reference: JalaliMonth; test: JalaliMonth } {
  const now = currentJalaliMonth(at);

  if (key === 'previous_month') {
    const test = previousMonth(now.jy, now.jm);
    return { reference: previousMonth(test.jy, test.jm), test };
  }

  if (key === 'same_month_each_year') {
    // Two years apart gives the widest comparison a single pair can make.
    return { reference: { jy: now.jy - 2, jm: now.jm }, test: { jy: now.jy, jm: now.jm } };
  }

  // same_month_last_year
  return { reference: { jy: now.jy - 1, jm: now.jm }, test: { jy: now.jy, jm: now.jm } };
}

/** Resolve a preset into a reference and test period. */
export function resolvePreset(
  key: PresetKey,
  at: Date = new Date(),
  locale: 'en' | 'fa' = 'en',
): { reference: Period; test: Period } {
  const { reference, test } = presetMonths(key, at);
  return customPeriods(reference, test, locale);
}

/** An explicit Jalali month pair, for the custom picker. */
export function customPeriods(
  reference: JalaliMonth,
  test: JalaliMonth,
  locale: 'en' | 'fa' = 'en',
): { reference: Period; test: Period } {
  return {
    reference: period(reference.jy, reference.jm, locale),
    test: period(test.jy, test.jm, locale),
  };
}
