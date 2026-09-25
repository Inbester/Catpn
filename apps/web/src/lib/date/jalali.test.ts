import { describe, expect, it } from 'vitest';
import {
  dateToJalali,
  formatJalali,
  gregorianToJalali,
  isJalaliLeapYear,
  jalaliMonthLength,
  jalaliMonthName,
  jalaliMonthRange,
  jalaliToDate,
  jalaliToGregorian,
} from './jalali';

describe('Jalali ↔ Gregorian conversion', () => {
  // Reference pairs: Nowruz dates and other well-known anchors.
  const pairs: Array<[[number, number, number], [number, number, number], string]> = [
    [[1404, 1, 1], [2025, 3, 21], 'Nowruz 1404'],
    [[1403, 1, 1], [2024, 3, 20], 'Nowruz 1403 (leap Gregorian)'],
    [[1405, 1, 1], [2026, 3, 21], 'Nowruz 1405'],
    [[1400, 1, 1], [2021, 3, 21], 'Nowruz 1400'],
    [[1399, 12, 30], [2021, 3, 20], 'last day of leap year 1399'],
    [[1398, 10, 11], [2020, 1, 1], 'start of 2020'],
    [[1403, 10, 12], [2025, 1, 1], 'start of 2025'],
    [[1354, 5, 13], [1975, 8, 4], 'a mid-1970s date'],
    [[1404, 6, 31], [2025, 9, 22], 'end of Shahrivar 1404'],
    [[1404, 7, 1], [2025, 9, 23], 'start of Mehr 1404'],
  ];

  it.each(pairs)('%s ↔ %s (%s)', (jalali, gregorian) => {
    const [jy, jm, jd] = jalali;
    const [gy, gm, gd] = gregorian;

    expect(jalaliToGregorian(jy, jm, jd)).toEqual({ gy, gm, gd });
    expect(gregorianToJalali(gy, gm, gd)).toEqual({ jy, jm, jd });
  });

  it('round-trips every day across a four-year span', () => {
    // Catches off-by-one errors at month and year boundaries, which would
    // silently shift which trades fall inside a forward-test period.
    let date = Date.UTC(2023, 0, 1);
    const end = Date.UTC(2027, 0, 1);

    while (date < end) {
      const d = new Date(date);
      const j = dateToJalali(d);
      const back = jalaliToDate(j.jy, j.jm, j.jd);
      expect(back.toISOString().slice(0, 10)).toBe(d.toISOString().slice(0, 10));
      date += 86_400_000;
    }
  });
});

describe('leap years and month lengths', () => {
  it.each([
    [1399, true],
    [1403, true],
    [1404, false],
    [1405, false],
    [1408, true],
  ])('year %i leap = %s', (jy, expected) => {
    expect(isJalaliLeapYear(jy)).toBe(expected);
  });

  it('gives 31 days to the first six months', () => {
    for (let jm = 1; jm <= 6; jm += 1) {
      expect(jalaliMonthLength(1404, jm)).toBe(31);
    }
  });

  it('gives 30 days to months seven through eleven', () => {
    for (let jm = 7; jm <= 11; jm += 1) {
      expect(jalaliMonthLength(1404, jm)).toBe(30);
    }
  });

  it('gives Esfand 29 days normally and 30 in a leap year', () => {
    expect(jalaliMonthLength(1404, 12)).toBe(29);
    expect(jalaliMonthLength(1403, 12)).toBe(30);
  });

  it('rejects an impossible month', () => {
    expect(() => jalaliMonthLength(1404, 13)).toThrow(RangeError);
  });
});

describe('jalaliMonthRange', () => {
  it('covers Farvardin 1404 as a half-open UTC range', () => {
    const { start, end } = jalaliMonthRange(1404, 1);
    expect(start.toISOString()).toBe('2025-03-21T00:00:00.000Z');
    expect(end.toISOString()).toBe('2025-04-21T00:00:00.000Z');
  });

  it('rolls over the year boundary at Esfand', () => {
    const { start, end } = jalaliMonthRange(1403, 12);
    expect(start.toISOString()).toBe('2025-02-19T00:00:00.000Z');
    // 1403 is a leap year, so Esfand has 30 days.
    expect(end.toISOString()).toBe('2025-03-21T00:00:00.000Z');
    const days = (end.getTime() - start.getTime()) / 86_400_000;
    expect(days).toBe(30);
  });

  it('matches the month length for every month of a year', () => {
    for (let jm = 1; jm <= 12; jm += 1) {
      const { start, end } = jalaliMonthRange(1404, jm);
      const days = (end.getTime() - start.getTime()) / 86_400_000;
      expect(days).toBe(jalaliMonthLength(1404, jm));
    }
  });
});

describe('formatting', () => {
  it('formats short and long styles', () => {
    const date = { jy: 1404, jm: 1, jd: 5 };
    expect(formatJalali(date)).toBe('1404-01-05');
    expect(formatJalali(date, { style: 'long' })).toBe('5 Farvardin 1404');
    expect(formatJalali(date, { style: 'long', locale: 'fa' })).toBe('5 فروردین 1404');
  });

  it('names months in both locales', () => {
    expect(jalaliMonthName(1)).toBe('Farvardin');
    expect(jalaliMonthName(12, 'fa')).toBe('اسفند');
  });
});
