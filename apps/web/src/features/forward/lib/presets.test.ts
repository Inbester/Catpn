import { describe, expect, it } from 'vitest';

import {
  currentMonth,
  customPeriods,
  monthLabel,
  presetMonths,
  previousMonth,
  resolvePreset,
} from './presets';

// A fixed moment inside March 2026, so the presets are deterministic.
const IN_MARCH_2026 = new Date(Date.UTC(2026, 2, 15));

describe('monthLabel', () => {
  it('names the month', () => {
    expect(monthLabel(2025, 3)).toBe('March 2025');
    expect(monthLabel(2025, 12)).toBe('December 2025');
  });

  it('refuses a month outside the year', () => {
    expect(() => monthLabel(2025, 13)).toThrow(RangeError);
  });
});

describe('previousMonth', () => {
  it('steps back within a year', () => {
    expect(previousMonth(2025, 5)).toEqual({ year: 2025, month: 4 });
  });

  it('rolls the year at January', () => {
    expect(previousMonth(2025, 1)).toEqual({ year: 2024, month: 12 });
  });
});

describe('currentMonth', () => {
  it('reads the month in UTC', () => {
    expect(currentMonth(IN_MARCH_2026)).toEqual({ year: 2026, month: 3 });
  });
});

describe('resolvePreset', () => {
  it('compares this month against the same month last year', () => {
    const { reference, test } = resolvePreset('same_month_last_year', IN_MARCH_2026);
    expect(reference.label).toBe('March 2025');
    expect(test.label).toBe('March 2026');
  });

  it('puts the older period first, because that is what a forward test asks', () => {
    const { reference, test } = resolvePreset('same_month_last_year', IN_MARCH_2026);
    expect(reference.start).toBeLessThan(test.start);
  });

  it('spans whole months on UTC boundaries', () => {
    // Bars close on UTC boundaries, so a period that began at local
    // midnight would include or miss an hour of them.
    const { reference, test } = resolvePreset('same_month_last_year', IN_MARCH_2026);
    expect(new Date(reference.start).toISOString()).toBe('2025-03-01T00:00:00.000Z');
    expect(new Date(reference.end).toISOString()).toBe('2025-04-01T00:00:00.000Z');
    expect(new Date(test.start).toISOString()).toBe('2026-03-01T00:00:00.000Z');
  });

  it('steps back two months for the previous-month preset', () => {
    const { reference, test } = resolvePreset('previous_month', IN_MARCH_2026);
    expect(test.label).toBe('February 2026');
    expect(reference.label).toBe('January 2026');
  });

  it('spans two years for the every-year preset', () => {
    const { reference, test } = resolvePreset('same_month_each_year', IN_MARCH_2026);
    expect(reference.label).toBe('March 2024');
    expect(test.label).toBe('March 2026');
  });
});

describe('customPeriods', () => {
  it('builds an explicit pair the picker asks for', () => {
    const { reference, test } = customPeriods({ year: 2025, month: 3 }, { year: 2026, month: 3 });

    expect(reference.label).toBe('March 2025');
    expect(test.label).toBe('March 2026');
    expect(new Date(reference.start).toISOString()).toBe('2025-03-01T00:00:00.000Z');
    expect(new Date(test.end).toISOString()).toBe('2026-04-01T00:00:00.000Z');
  });

  it('rolls December into the next January', () => {
    const { test } = customPeriods({ year: 2025, month: 1 }, { year: 2025, month: 12 });
    expect(new Date(test.start).toISOString()).toBe('2025-12-01T00:00:00.000Z');
    expect(new Date(test.end).toISOString()).toBe('2026-01-01T00:00:00.000Z');
  });

  it('agrees with the preset it stands in for', () => {
    const months = presetMonths('same_month_last_year', IN_MARCH_2026);
    expect(customPeriods(months.reference, months.test)).toEqual(
      resolvePreset('same_month_last_year', IN_MARCH_2026),
    );
  });
});
