import { describe, expect, it } from 'vitest';

import {
  addChoice,
  choiceLabel,
  defaultChoices,
  inputOptions,
  lineLabel,
  MAX_INDICATORS,
  nextKey,
  paramProblem,
  parseSaved,
  pruneRequired,
  removeChoice,
  setInput,
  type IndicatorChoice,
  type IndicatorSpec,
} from './indicators';

const SPECS: IndicatorSpec[] = [
  {
    id: 'ema',
    name: 'EMA',
    description: '',
    takes_input: true,
    params: [{ name: 'length', label: 'Length', default: 20, min: 2, max: 500, integer: true }],
    outputs: [{ key: 'ema', label: '' }],
  },
  {
    id: 'rsi',
    name: 'RSI',
    description: '',
    takes_input: true,
    params: [{ name: 'length', label: 'Length', default: 14, min: 2, max: 100, integer: true }],
    outputs: [{ key: 'rsi', label: '' }],
  },
  {
    id: 'macd',
    name: 'MACD',
    description: '',
    takes_input: true,
    params: [
      { name: 'fast', label: 'Fast', default: 12, min: 2, max: 200, integer: true },
      { name: 'slow', label: 'Slow', default: 26, min: 3, max: 400, integer: true },
      { name: 'signal', label: 'Signal', default: 9, min: 2, max: 100, integer: true },
    ],
    outputs: [
      { key: 'macd', label: 'line' },
      { key: 'signal', label: 'signal' },
    ],
  },
  {
    id: 'bb',
    name: 'Bollinger',
    description: '',
    takes_input: true,
    params: [
      { name: 'length', label: 'Length', default: 20, min: 2, max: 500, integer: true },
      { name: 'multiplier', label: 'Width', default: 2, min: 0.5, max: 5, integer: false },
    ],
    outputs: [{ key: 'upper', label: 'upper' }],
  },
];

const rsiThenEma: IndicatorChoice[] = [
  { key: 'i1', id: 'rsi', params: { length: 14 }, input: 'close' },
  { key: 'i2', id: 'ema', params: { length: 9 }, input: 'i1.rsi' },
];

describe('labels', () => {
  it('names an indicator applied to another the way the server does', () => {
    expect(choiceLabel(rsiThenEma, SPECS, 'i2')).toBe('EMA 9 of RSI 14');
  });

  it('names one line of a multi-line indicator', () => {
    const choices = addChoice([], SPECS, 'macd');
    expect(lineLabel(choices, SPECS, 'i1.signal')).toBe('MACD 12/26/9 signal');
  });

  it('formats fractional settings like the server', () => {
    const choices: IndicatorChoice[] = [
      { key: 'i1', id: 'bb', params: { length: 20, multiplier: 2.5 }, input: 'close' },
    ];
    expect(choiceLabel(choices, SPECS, 'i1')).toBe('Bollinger 20/2.5');
  });
});

describe('inputs', () => {
  it('offers price and only the lines listed above', () => {
    // Order is what rules out a loop: nothing can feed what fed it.
    const choices = [...rsiThenEma, ...addChoice(rsiThenEma, SPECS, 'macd').slice(2)];
    expect(inputOptions(choices, SPECS, 0).map((o) => o.value)).toEqual(['close']);
    expect(inputOptions(choices, SPECS, 2).map((o) => o.value)).toEqual([
      'close',
      'i1.rsi',
      'i2.ema',
    ]);
  });

  it('points a dependant back at price when its input is removed', () => {
    const left = removeChoice(rsiThenEma, 'i1');
    expect(left).toEqual([{ key: 'i2', id: 'ema', params: { length: 9 }, input: 'close' }]);
  });

  it('can switch what an indicator is applied to', () => {
    expect(setInput(rsiThenEma, 'i2', 'close')[1]?.input).toBe('close');
  });
});

describe('adding', () => {
  it('fills in defaults and a fresh key', () => {
    const choices = addChoice(defaultChoices(), SPECS, 'rsi');
    expect(choices.at(-1)).toEqual({
      key: 'i4',
      id: 'rsi',
      params: { length: 14 },
      input: 'close',
    });
  });

  it('reuses a key freed by a removal', () => {
    expect(nextKey(removeChoice(defaultChoices(), 'i2'))).toBe('i2');
  });

  it('stops at the cap', () => {
    let choices: IndicatorChoice[] = [];
    for (let n = 0; n < MAX_INDICATORS + 2; n += 1) choices = addChoice(choices, SPECS, 'ema');
    expect(choices).toHaveLength(MAX_INDICATORS);
  });
});

describe('settings', () => {
  const length = SPECS[0]!.params[0]!;

  it('names a value outside its range', () => {
    expect(paramProblem(length, 1)).toBe('Length must be between 2 and 500');
    expect(paramProblem(length, 9.5)).toBe('Length must be a whole number');
    expect(paramProblem(length, 9)).toBeNull();
  });
});

describe('required indicators', () => {
  it('drops a requirement whose indicator is gone, and keeps at most three', () => {
    expect(pruneRequired(['i1', 'i9'], rsiThenEma)).toEqual(['i1']);
    const many = defaultChoices().concat(addChoice(defaultChoices(), SPECS, 'rsi').slice(3));
    expect(pruneRequired(['i1', 'i2', 'i3', 'i4'], many)).toHaveLength(3);
  });
});

describe('saved state', () => {
  it('restores what was saved', () => {
    const restored = parseSaved({
      choices: rsiThenEma,
      mode: 'require',
      required: ['i1', 'gone'],
      conditions: 2,
    });
    expect(restored).toEqual({
      choices: rsiThenEma,
      mode: 'require',
      required: ['i1'],
      conditions: 2,
    });
  });

  it('ignores something that is not a saved picker', () => {
    expect(parseSaved(null)).toBeNull();
    expect(parseSaved({ other: 1 })).toBeNull();
    expect(parseSaved({ choices: [], mode: 'weird', conditions: 9 })).toEqual({
      choices: [],
      mode: 'any',
      required: [],
      conditions: 3,
    });
  });
});
