import { describe, expect, it } from 'vitest';

import { describeResult, routeIds } from './network';

describe('routeIds', () => {
  it('keeps the order the user chose', () => {
    expect(routeIds('a', 'b')).toEqual(['a', 'b']);
  });

  it('means the server when nothing is chosen', () => {
    expect(routeIds('', '')).toEqual([]);
  });

  it('drops a fallback that repeats the primary', () => {
    // The server refuses a tunnel listed twice; the page should not
    // turn a harmless choice into an error.
    expect(routeIds('a', 'a')).toEqual(['a']);
  });

  it('allows a fallback with no primary', () => {
    expect(routeIds('', 'b')).toEqual(['b']);
  });
});

describe('describeResult', () => {
  it('says when a tunnel was never tested', () => {
    expect(describeResult({})).toBe('Never tested.');
  });

  it('shows the measurement that came back', () => {
    expect(
      describeResult({
        state: 'ok',
        exit_ip: '203.0.113.50',
        latency_ms: 84.4,
        jitter_ms: 3.2,
        loss_percent: 0,
      }),
    ).toBe('exit 203.0.113.50 · 84 ms · ±3 ms jitter · 0% loss');
  });

  it('shows the reason instead of numbers when the test failed', () => {
    // A bar invented from nothing would be believed.
    expect(describeResult({ state: 'failed', detail: 'handshake timed out' })).toBe(
      'handshake timed out',
    );
  });
});
