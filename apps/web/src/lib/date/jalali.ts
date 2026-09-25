/**
 * Jalali (Solar Hijri) calendar conversion.
 *
 * SPEC D11: Jalali support is required from day one. The forward test uses
 * Jalali month presets ("Farvardin 1404 vs 1405"), so the conversion has to
 * be exact rather than approximate — a month boundary that is one day off
 * would silently shift which trades land in a reference period.
 *
 * The algorithm is the arithmetic one from the Persian calendar's 33-year
 * leap cycle, via the Julian Day Number. It is exact for 1178–1633 AP
 * (1800–2255 CE), which covers every date this product can be given.
 */

export interface JalaliDate {
  /** Year in the Solar Hijri era, e.g. 1404. */
  jy: number;
  /** Month, 1 = Farvardin … 12 = Esfand. */
  jm: number;
  /** Day of month, 1-31. */
  jd: number;
}

export interface GregorianDate {
  gy: number;
  /** Month, 1 = January … 12 = December. */
  gm: number;
  gd: number;
}

export const JALALI_MONTHS_EN = [
  'Farvardin',
  'Ordibehesht',
  'Khordad',
  'Tir',
  'Mordad',
  'Shahrivar',
  'Mehr',
  'Aban',
  'Azar',
  'Dey',
  'Bahman',
  'Esfand',
] as const;

export const JALALI_MONTHS_FA = [
  'فروردین',
  'اردیبهشت',
  'خرداد',
  'تیر',
  'مرداد',
  'شهریور',
  'مهر',
  'آبان',
  'آذر',
  'دی',
  'بهمن',
  'اسفند',
] as const;

/** Floor division that behaves correctly for negative operands. */
function div(a: number, b: number): number {
  return Math.floor(a / b);
}

/**
 * Leap-year and epoch data for the Jalali year containing `jy`.
 *
 * Returns the number of leap years since the epoch (`leap`), the Gregorian
 * year the Jalali year starts in (`gy`), and the March day it starts on.
 */
function jalCal(jy: number): { leap: number; gy: number; march: number } {
  // Breakpoints of the 2820-year cycle used by the arithmetic calendar.
  const breaks = [
    -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394,
    2456, 3178,
  ];

  const gy = jy + 621;
  let leapJ = -14;
  let jp = breaks[0] as number;

  if (jy < jp || jy >= (breaks[breaks.length - 1] as number)) {
    throw new RangeError(`Jalali year ${jy} is outside the supported range.`);
  }

  let jump = 0;
  for (let i = 1; i < breaks.length; i += 1) {
    const jm = breaks[i] as number;
    jump = jm - jp;
    if (jy < jm) break;
    leapJ += div(jump, 33) * 8 + div(jump % 33, 4);
    jp = jm;
  }

  let n = jy - jp;
  leapJ += div(n, 33) * 8 + div((n % 33) + 3, 4);
  if (jump % 33 === 4 && jump - n === 4) leapJ += 1;

  // Leap years in the Gregorian calendar up to the same point.
  const leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150;
  const march = 20 + leapJ - leapG;

  if (jump - n < 6) n = n - jump + div(jump + 4, 33) * 33;
  let leap = (((n + 1) % 33) - 1) % 4;
  if (leap === -1) leap = 4;

  return { leap, gy, march };
}

/**
 * True when the given Jalali year has 366 days.
 *
 * `jalCal` reports `leap` as the offset to the next leap year, so zero means
 * "this year is the leap one".
 */
export function isJalaliLeapYear(jy: number): boolean {
  return jalCal(jy).leap === 0;
}

/** Days in a Jalali month: 31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29/30. */
export function jalaliMonthLength(jy: number, jm: number): number {
  if (jm < 1 || jm > 12) throw new RangeError(`Jalali month ${jm} is out of range.`);
  if (jm <= 6) return 31;
  if (jm <= 11) return 30;
  return isJalaliLeapYear(jy) ? 30 : 29;
}

/**
 * Julian Day Number for a proleptic Gregorian date.
 *
 * The Fliegel & Van Flandern algorithm. `gregorianToJdn(2000, 1, 1)` is
 * 2451545, the standard J2000.0 epoch, which is the anchor the unit tests
 * check against.
 */
export function gregorianToJdn(gy: number, gm: number, gd: number): number {
  const a = div(14 - gm, 12);
  const y = gy + 4800 - a;
  const m = gm + 12 * a - 3;
  return gd + div(153 * m + 2, 5) + 365 * y + div(y, 4) - div(y, 100) + div(y, 400) - 32045;
}

/** Gregorian date from a Julian Day Number. The inverse of the above. */
export function jdnToGregorian(jdn: number): GregorianDate {
  const a = jdn + 32044;
  const b = div(4 * a + 3, 146097);
  const c = a - div(146097 * b, 4);
  const d = div(4 * c + 3, 1461);
  const e = c - div(1461 * d, 4);
  const m = div(5 * e + 2, 153);
  return {
    gy: 100 * b + d - 4800 + div(m, 10),
    gm: m + 3 - 12 * div(m, 10),
    gd: e - div(153 * m + 2, 5) + 1,
  };
}

/** Julian Day Number for a Jalali date. */
export function jalaliToJdn(jy: number, jm: number, jd: number): number {
  const { gy, march } = jalCal(jy);
  return gregorianToJdn(gy, 3, march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1;
}

/** Jalali date from a Julian Day Number. */
export function jdnToJalali(jdn: number): JalaliDate {
  const { gy } = jdnToGregorian(jdn);
  let jy = gy - 621;
  const { leap, march } = jalCal(jy);
  const jdn1f = gregorianToJdn(gy, 3, march);

  let k = jdn - jdn1f;
  if (k >= 0) {
    if (k <= 185) {
      // First half of the year: six 31-day months.
      return { jy, jm: 1 + div(k, 31), jd: (k % 31) + 1 };
    }
    k -= 186;
  } else {
    // Before Farvardin 1: fall back into the previous year.
    jy -= 1;
    k += 179;
    if (leap === 1) k += 1;
  }

  return { jy, jm: 7 + div(k, 30), jd: (k % 30) + 1 };
}

export function jalaliToGregorian(jy: number, jm: number, jd: number): GregorianDate {
  return jdnToGregorian(jalaliToJdn(jy, jm, jd));
}

export function gregorianToJalali(gy: number, gm: number, gd: number): JalaliDate {
  return jdnToJalali(gregorianToJdn(gy, gm, gd));
}

/**
 * Convert a `Date` to its Jalali parts.
 *
 * Reads the UTC components, so the caller decides the timezone by shifting
 * the Date beforehand. Bar boundaries are UTC throughout the product
 * (SPEC §3.1), so this keeps the two consistent.
 */
export function dateToJalali(date: Date): JalaliDate {
  return gregorianToJalali(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate());
}

/** Build a UTC `Date` at midnight from Jalali parts. */
export function jalaliToDate(jy: number, jm: number, jd: number): Date {
  const { gy, gm, gd } = jalaliToGregorian(jy, jm, jd);
  return new Date(Date.UTC(gy, gm - 1, gd));
}

/** The UTC half-open range `[start, end)` covering one Jalali month. */
export function jalaliMonthRange(jy: number, jm: number): { start: Date; end: Date } {
  const start = jalaliToDate(jy, jm, 1);
  const nextYear = jm === 12 ? jy + 1 : jy;
  const nextMonth = jm === 12 ? 1 : jm + 1;
  return { start, end: jalaliToDate(nextYear, nextMonth, 1) };
}

export function jalaliMonthName(jm: number, locale: 'en' | 'fa' = 'en'): string {
  const months = locale === 'fa' ? JALALI_MONTHS_FA : JALALI_MONTHS_EN;
  const name = months[jm - 1];
  if (!name) throw new RangeError(`Jalali month ${jm} is out of range.`);
  return name;
}

/** Format a Jalali date as `1404-01-15`, or `15 Farvardin 1404` when long. */
export function formatJalali(
  date: JalaliDate,
  options: { style?: 'short' | 'long'; locale?: 'en' | 'fa' } = {},
): string {
  const { style = 'short', locale = 'en' } = options;
  if (style === 'long') {
    return `${date.jd} ${jalaliMonthName(date.jm, locale)} ${date.jy}`;
  }
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.jy}-${pad(date.jm)}-${pad(date.jd)}`;
}
