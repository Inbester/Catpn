import { describe, expect, it } from 'vitest';

import { combinationCount, expandRange, prune } from './grid';

describe('expandRange', () => {
  it('walks whole numbers inclusively', () => {
    expect(expandRange({ from: 10, to: 30, step: 10 })).toEqual([10, 20, 30]);
  });

  it('keeps a fractional step exact', () => {
    // Accumulating 0.1 three times gives 0.30000000000000004, which would
    // be hashed into a strategy version as a different number than shown.
    expect(expandRange({ from: 0.1, to: 0.5, step: 0.1 })).toEqual([0.1, 0.2, 0.3, 0.4, 0.5]);
  });

  it('does not drop the last value to floating point', () => {
    expect(expandRange({ from: 1, to: 2, step: 0.2 })).toEqual([1, 1.2, 1.4, 1.6, 1.8, 2]);
  });

  it('keeps the stated end when the step does not divide the span', () => {
    expect(expandRange({ from: 10, to: 25, step: 10 })).toEqual([10, 20, 25]);
  });

  it('is a single value when both ends agree', () => {
    expect(expandRange({ from: 14, to: 14, step: 1 })).toEqual([14]);
  });

  it('refuses a range that cannot terminate', () => {
    expect(expandRange({ from: 1, to: 10, step: 0 })).toEqual([]);
    expect(expandRange({ from: 1, to: 10, step: -1 })).toEqual([]);
    expect(expandRange({ from: 10, to: 1, step: 1 })).toEqual([]);
    expect(expandRange({ from: Number.NaN, to: 1, step: 1 })).toEqual([]);
  });
});

describe('combinationCount', () => {
  it('multiplies across parameters', () => {
    expect(combinationCount({ fast: [5, 10], slow: [20, 30, 40] })).toBe(6);
  });

  it('is one for an empty grid', () => {
    expect(combinationCount({})).toBe(1);
  });
});

describe('prune', () => {
  it('drops parameters that hold a single value', () => {
    // Sending them would make the engine re-run identical backtests and
    // report a "chosen" parameter nothing chose.
    expect(prune({ fast: [10], slow: [20, 30] })).toEqual({ slow: [20, 30] });
  });
});
