/**
 * Period presets for the forward test (SPEC §3.3).
 *
 * Gregorian months. Presets resolve to explicit UTC ranges here, in the
 * browser, and the API is sent epoch milliseconds — so there is one date
 * implementation rather than two that could drift.
 */

export interface Period {
  label: string;
  start: number;
  end: number;
}

export interface CalendarMonth {
  year: number;
  /** 1–12, so a month reads the way it is spoken rather than zero-based. */
  month: number;
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
    description: 'This month against the same month last year.',
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

export const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
] as const;

/** A readable label, e.g. "March 2025". */
export function monthLabel(year: number, month: number): string {
  const name = MONTH_NAMES[month - 1];
  if (!name) throw new RangeError(`Month ${month} is out of range.`);
  return `${name} ${year}`;
}

function period(year: number, month: number): Period {
  // UTC throughout: bars close on UTC boundaries, so a period that began
  // at local midnight would include or miss an hour of them.
  const start = Date.UTC(year, month - 1, 1);
  const end = Date.UTC(month === 12 ? year + 1 : year, month === 12 ? 0 : month, 1);
  return { label: monthLabel(year, month), start, end };
}

/** The month a moment falls in, in UTC. */
export function currentMonth(at: Date = new Date()): CalendarMonth {
  return { year: at.getUTCFullYear(), month: at.getUTCMonth() + 1 };
}

/** Step back one month, rolling the year at January. */
export function previousMonth(year: number, month: number): CalendarMonth {
  return month === 1 ? { year: year - 1, month: 12 } : { year, month: month - 1 };
}

/**
 * The months a preset picks out.
 *
 * The *reference* is always the older month and the *test* the newer one:
 * a forward test asks whether what held before still holds now, so running
 * it the other way round would answer nothing.
 */
export function presetMonths(
  key: PresetKey,
  at: Date = new Date(),
): { reference: CalendarMonth; test: CalendarMonth } {
  const now = currentMonth(at);

  if (key === 'previous_month') {
    const test = previousMonth(now.year, now.month);
    return { reference: previousMonth(test.year, test.month), test };
  }

  if (key === 'same_month_each_year') {
    // Two years apart gives the widest comparison a single pair can make.
    return {
      reference: { year: now.year - 2, month: now.month },
      test: { year: now.year, month: now.month },
    };
  }

  // same_month_last_year
  return {
    reference: { year: now.year - 1, month: now.month },
    test: { year: now.year, month: now.month },
  };
}

/** Resolve a preset into a reference and test period. */
export function resolvePreset(
  key: PresetKey,
  at: Date = new Date(),
): { reference: Period; test: Period } {
  const { reference, test } = presetMonths(key, at);
  return customPeriods(reference, test);
}

/** An explicit month pair, for the custom picker. */
export function customPeriods(
  reference: CalendarMonth,
  test: CalendarMonth,
): { reference: Period; test: Period } {
  return {
    reference: period(reference.year, reference.month),
    test: period(test.year, test.month),
  };
}
