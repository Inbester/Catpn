import { describe, expect, it } from 'vitest';

import { formatCountdown, secondsUntilClose } from './useCountdown';

describe('secondsUntilClose', () => {
  it('measures to the next UTC boundary, not from "now"', () => {
    // SPEC §3.1: bar boundaries are UTC, so a 1m bar closes on the minute.
    const at = Date.UTC(2026, 0, 1, 12, 30, 20);
    expect(secondsUntilClose(at, 60)).toBe(40);
  });

  it('handles an hourly bar', () => {
    const at = Date.UTC(2026, 0, 1, 12, 30, 0);
    expect(secondsUntilClose(at, 3600)).toBe(1800);
  });

  it('is a full interval exactly on a boundary', () => {
    const at = Date.UTC(2026, 0, 1, 12, 0, 0);
    expect(secondsUntilClose(at, 900)).toBe(900);
  });

  it('handles a daily bar', () => {
    const at = Date.UTC(2026, 0, 1, 18, 0, 0);
    expect(secondsUntilClose(at, 86_400)).toBe(6 * 3600);
  });
});

describe('formatCountdown', () => {
  it('uses mm:ss below an hour', () => {
    expect(formatCountdown(65, 900)).toBe('01:05');
    expect(formatCountdown(9, 60)).toBe('00:09');
  });

  it('uses hh:mm:ss from an hour up', () => {
    expect(formatCountdown(3661, 3600)).toBe('01:01:01');
    expect(formatCountdown(59, 14_400)).toBe('00:00:59');
  });

  it('uses days and hours for daily bars and longer', () => {
    expect(formatCountdown(2 * 86_400 + 4 * 3600, 86_400)).toBe('2d 04h');
  });

  it('never goes negative', () => {
    expect(formatCountdown(-5, 60)).toBe('00:00');
  });
});
