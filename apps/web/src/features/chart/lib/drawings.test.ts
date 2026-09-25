import { describe, expect, it } from 'vitest';

import {
  createDrawing,
  drawingScope,
  isDrawing,
  parseChartDocument,
  POINTS_REQUIRED,
} from './drawings';

describe('createDrawing', () => {
  it('anchors points in time and price, not pixels', () => {
    const drawing = createDrawing(
      'trend',
      [
        { time: 1_700_000_000_000, price: 64_000 },
        { time: 1_700_000_600_000, price: 65_000 },
      ],
      '#6EA8FE',
    );
    expect(drawing.points[0]).toEqual({ time: 1_700_000_000_000, price: 64_000 });
    expect(drawing.visible).toBe(true);
    expect(drawing.locked).toBe(false);
  });

  it('gives every drawing a unique id', () => {
    const a = createDrawing('horizontal', [{ time: 1, price: 2 }], '#fff');
    const b = createDrawing('horizontal', [{ time: 1, price: 2 }], '#fff');
    expect(a.id).not.toBe(b.id);
  });
});

describe('drawingScope', () => {
  it('scopes per symbol and timeframe (SPEC §3.1)', () => {
    expect(drawingScope('BTCUSDT', '15m')).toBe('BTCUSDT:15m');
    expect(drawingScope('BTCUSDT', '15m')).not.toBe(drawingScope('BTCUSDT', '1h'));
    expect(drawingScope('BTCUSDT', '15m')).not.toBe(drawingScope('ETHUSDT', '15m'));
  });
});

describe('isDrawing', () => {
  const valid = {
    id: 'd-1',
    tool: 'trend',
    points: [
      { time: 1, price: 2 },
      { time: 3, price: 4 },
    ],
    color: '#fff',
    width: 1,
    style: 'solid',
    locked: false,
    visible: true,
    createdAt: 0,
  };

  it('accepts a well-formed drawing', () => {
    expect(isDrawing(valid)).toBe(true);
  });

  it('rejects a tool it does not know', () => {
    expect(isDrawing({ ...valid, tool: 'lasso' })).toBe(false);
  });

  it('rejects the wrong number of anchors', () => {
    expect(isDrawing({ ...valid, points: [{ time: 1, price: 2 }] })).toBe(false);
  });

  it('rejects a non-finite coordinate', () => {
    expect(
      isDrawing({
        ...valid,
        points: [
          { time: 1, price: Number.NaN },
          { time: 3, price: 4 },
        ],
      }),
    ).toBe(false);
  });

  it('rejects junk', () => {
    expect(isDrawing(null)).toBe(false);
    expect(isDrawing('trend')).toBe(false);
    expect(isDrawing({})).toBe(false);
  });

  it('knows how many anchors each tool needs', () => {
    expect(POINTS_REQUIRED.horizontal).toBe(1);
    expect(POINTS_REQUIRED.trend).toBe(2);
    expect(POINTS_REQUIRED.rectangle).toBe(2);
  });
});

describe('parseChartDocument', () => {
  it('reads a well-formed document', () => {
    const document = parseChartDocument({
      drawings: [
        {
          id: 'd-1',
          tool: 'horizontal',
          points: [{ time: 1, price: 2 }],
          color: '#fff',
          width: 1,
          style: 'solid',
          locked: false,
          visible: true,
          createdAt: 0,
        },
      ],
      indicators: [{ id: 'ema' }],
      chartType: 'line',
      priceScaleMode: 'logarithmic',
    });

    expect(document?.drawings).toHaveLength(1);
    expect(document?.chartType).toBe('line');
    expect(document?.priceScaleMode).toBe('logarithmic');
  });

  it('drops malformed drawings instead of failing the whole load', () => {
    // Local storage can hold whatever an older build wrote.
    const document = parseChartDocument({
      drawings: [
        { id: 'ok', tool: 'horizontal', points: [{ time: 1, price: 2 }] },
        { nonsense: true },
        null,
      ],
    });
    expect(document?.drawings).toHaveLength(1);
  });

  it('falls back to defaults for missing fields', () => {
    const document = parseChartDocument({});
    expect(document).toEqual({
      drawings: [],
      indicators: [],
      chartType: 'candles',
      priceScaleMode: 'normal',
    });
  });

  it('returns null for something that is not a document', () => {
    expect(parseChartDocument(null)).toBeNull();
    expect(parseChartDocument('nope')).toBeNull();
  });
});
