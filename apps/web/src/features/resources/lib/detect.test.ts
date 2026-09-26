import { describe, expect, it } from 'vitest';

import { workerCount } from './detect';

describe('workerCount', () => {
  it('always leaves one core free', () => {
    // A machine whose every core is busy cannot redraw the page that is
    // showing the progress.
    expect(workerCount(8, 100)).toBe(7);
  });

  it('scales with the share the user allowed', () => {
    expect(workerCount(9, 50)).toBe(4);
    expect(workerCount(9, 25)).toBe(2);
  });

  it('never returns zero workers', () => {
    expect(workerCount(8, 0)).toBe(1);
    expect(workerCount(2, 1)).toBe(1);
  });

  it('copes with a browser that reports nothing', () => {
    expect(workerCount(undefined, 50)).toBe(1);
    expect(workerCount(1, 100)).toBe(1);
  });
});
