import { describe, expect, it } from 'vitest';

import { jalaliToDate } from '@/lib/date/jalali';
import {
  currentJalaliMonth,
  customPeriods,
  monthLabel,
  presetMonths,
  previousMonth,
  resolvePreset,
} from './presets';

// A fixed moment inside Farvardin 1405, so the presets are deterministic.
const IN_FARVARDIN_1405 = jalaliToDate(1405, 1, 15);

describe('monthLabel', () => {
  it('names the month in English and Persian', () => {
    expect(monthLabel(1404, 1)).toBe('Farvardin 1404');
    expect(monthLabel(1404, 1, 'fa')).toBe('فروردین 1404');
  });
});

describe('previousMonth', () => {
  it('steps back within a year', () => {
    expect(previousMonth(1404, 5)).toEqual({ jy: 1404, jm: 4 });
  });

  it('rolls the year at Farvardin', () => {
    expect(previousMonth(1404, 1)).toEqual({ jy: 1403, jm: 12 });
  });
});

describe('currentJalaliMonth', () => {
  it('reads the Jalali month a date falls in', () => {
    const month = currentJalaliMonth(IN_FARVARDIN_1405);
    expect(month.jy).toBe(1405);
    expect(month.jm).toBe(1);
  });
});

describe('resolvePreset', () => {
  it('compares this month with the same month last year', () => {
    // The SPEC §8 acceptance example: Farvardin 1404 against 1405.
    const { reference, test } = resolvePreset('same_month_last_year', IN_FARVARDIN_1405);
    expect(reference.label).toBe('Farvardin 1404');
    expect(test.label).toBe('Farvardin 1405');
  });

  it('puts the older period first', () => {
    // A forward test asks whether what held before still holds now.
    for (const key of ['same_month_last_year', 'previous_month', 'same_month_each_year'] as const) {
      const { reference, test } = resolvePreset(key, IN_FARVARDIN_1405);
      expect(reference.start, key).toBeLessThan(test.start);
    }
  });

  it('resolves to real UTC month boundaries', () => {
    const { reference, test } = resolvePreset('same_month_last_year', IN_FARVARDIN_1405);
    // Farvardin 1404 began on 21 March 2025.
    expect(new Date(reference.start).toISOString()).toBe('2025-03-21T00:00:00.000Z');
    expect(new Date(reference.end).toISOString()).toBe('2025-04-21T00:00:00.000Z');
    expect(new Date(test.start).toISOString()).toBe('2026-03-21T00:00:00.000Z');
  });

  it('gives each period a whole month of span', () => {
    const { reference, test } = resolvePreset('same_month_last_year', IN_FARVARDIN_1405);
    for (const p of [reference, test]) {
      const days = (p.end - p.start) / 86_400_000;
      expect(days).toBe(31); // Farvardin always has 31 days.
    }
  });

  it('steps back two months for the previous-month preset', () => {
    const { reference, test } = resolvePreset('previous_month', IN_FARVARDIN_1405);
    expect(test.label).toBe('Esfand 1404');
    expect(reference.label).toBe('Bahman 1404');
  });

  it('spans two years for the every-year preset', () => {
    const { reference, test } = resolvePreset('same_month_each_year', IN_FARVARDIN_1405);
    expect(reference.label).toBe('Farvardin 1403');
    expect(test.label).toBe('Farvardin 1405');
  });
});

describe('customPeriods', () => {
  it('builds the Farvardin 1404 vs 1405 pair the picker asks for', () => {
    // The Phase 3 acceptance case. The preset only reaches it while today
    // happens to fall in Farvardin, so the picker has to reach it directly.
    const { reference, test } = customPeriods({ jy: 1404, jm: 1 }, { jy: 1405, jm: 1 });

    expect(reference.label).toBe('Farvardin 1404');
    expect(test.label).toBe('Farvardin 1405');
    expect(new Date(reference.start).toISOString()).toBe('2025-03-21T00:00:00.000Z');
    expect(new Date(reference.end).toISOString()).toBe('2025-04-21T00:00:00.000Z');
    expect(new Date(test.start).toISOString()).toBe('2026-03-21T00:00:00.000Z');
    expect(new Date(test.end).toISOString()).toBe('2026-04-21T00:00:00.000Z');
  });

  it('agrees with the preset it stands in for', () => {
    const months = presetMonths('same_month_last_year', IN_FARVARDIN_1405);
    expect(customPeriods(months.reference, months.test)).toEqual(
      resolvePreset('same_month_last_year', IN_FARVARDIN_1405),
    );
  });
});
