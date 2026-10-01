/**
 * The indicators a Discover search is built from, as the picker edits them.
 *
 * The server owns the catalog and validates every choice; this module only
 * keeps the client's list coherent while it is edited — stable keys, an
 * input that always points at something that still exists, labels that
 * match the ones the server will use in its results.
 */

export interface IndicatorParamSpec {
  name: string;
  label: string;
  default: number;
  min: number;
  max: number;
  integer: boolean;
}

export interface IndicatorSpec {
  id: string;
  name: string;
  description: string;
  /** True: works on one series (price, or another indicator's line). */
  takes_input: boolean;
  params: IndicatorParamSpec[];
  outputs: { key: string; label: string }[];
}

export interface IndicatorChoice {
  /** Stable while editing, so an input reference survives a settings change. */
  key: string;
  id: string;
  params: Record<string, number>;
  /** 'close', or `${key}.${output}` of an indicator listed before this one. */
  input: string;
}

export type CombineMode = 'any' | 'mix' | 'require';

export const PRICE_INPUT = 'close';
export const MAX_INDICATORS = 8;
export const MAX_REQUIRED = 3;

/** Python's `:g` for the numbers settings use, so labels match the server's. */
function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toPrecision(6)));
}

function specFor(specs: IndicatorSpec[], id: string): IndicatorSpec | undefined {
  return specs.find((spec) => spec.id === id);
}

/** "EMA 9", or "EMA 9 of RSI 14" when it is applied to another indicator. */
export function choiceLabel(
  choices: IndicatorChoice[],
  specs: IndicatorSpec[],
  key: string,
): string {
  const choice = choices.find((item) => item.key === key);
  const spec = choice ? specFor(specs, choice.id) : undefined;
  if (!choice || !spec) return key;
  const values = spec.params.map((param) =>
    formatNumber(choice.params[param.name] ?? param.default),
  );
  const own = values.length ? `${spec.name} ${values.join('/')}` : spec.name;
  if (!spec.takes_input || choice.input === PRICE_INPUT) return own;
  return `${own} of ${lineLabel(choices, specs, choice.input)}`;
}

/** The label of one line: 'Price', 'RSI 14', 'MACD 12/26/9 signal'. */
export function lineLabel(
  choices: IndicatorChoice[],
  specs: IndicatorSpec[],
  line: string,
): string {
  if (line === PRICE_INPUT) return 'Price';
  const [key, output] = line.split('.');
  const choice = choices.find((item) => item.key === key);
  const spec = choice ? specFor(specs, choice.id) : undefined;
  const base = choiceLabel(choices, specs, key ?? '');
  if (!spec || spec.outputs.length === 1) return base;
  const label = spec.outputs.find((item) => item.key === output)?.label ?? output;
  return `${base} ${label}`;
}

/** What `choices[index]` may be applied to: price, then every line above it. */
export function inputOptions(
  choices: IndicatorChoice[],
  specs: IndicatorSpec[],
  index: number,
): { value: string; label: string }[] {
  const options = [{ value: PRICE_INPUT, label: 'Price' }];
  for (const choice of choices.slice(0, index)) {
    const spec = specFor(specs, choice.id);
    for (const output of spec?.outputs ?? []) {
      const value = `${choice.key}.${output.key}`;
      options.push({ value, label: lineLabel(choices, specs, value) });
    }
  }
  return options;
}

/** The next unused key: i1, i2, … */
export function nextKey(choices: IndicatorChoice[]): string {
  const used = new Set(choices.map((item) => item.key));
  let n = 1;
  while (used.has(`i${n}`)) n += 1;
  return `i${n}`;
}

export function addChoice(
  choices: IndicatorChoice[],
  specs: IndicatorSpec[],
  id: string,
): IndicatorChoice[] {
  const spec = specFor(specs, id);
  if (!spec || choices.length >= MAX_INDICATORS) return choices;
  const params = Object.fromEntries(spec.params.map((param) => [param.name, param.default]));
  return [...choices, { key: nextKey(choices), id, params, input: PRICE_INPUT }];
}

/**
 * Remove one, and point anything that was fed from it back at price.
 *
 * Done here rather than left to the server's refusal: deleting RSI should
 * not turn "EMA 9 of RSI" into an error the user has to go and find.
 */
export function removeChoice(choices: IndicatorChoice[], key: string): IndicatorChoice[] {
  return choices
    .filter((item) => item.key !== key)
    .map((item) => (item.input.split('.')[0] === key ? { ...item, input: PRICE_INPUT } : item));
}

export function setParam(
  choices: IndicatorChoice[],
  key: string,
  name: string,
  value: number,
): IndicatorChoice[] {
  return choices.map((item) =>
    item.key === key ? { ...item, params: { ...item.params, [name]: value } } : item,
  );
}

export function setInput(
  choices: IndicatorChoice[],
  key: string,
  input: string,
): IndicatorChoice[] {
  return choices.map((item) => (item.key === key ? { ...item, input } : item));
}

/** A setting's problem in words, or null. The server checks too; this is for typing. */
export function paramProblem(param: IndicatorParamSpec, value: number): string | null {
  if (!Number.isFinite(value)) return `${param.label} must be a number`;
  if (value < param.min || value > param.max) {
    return `${param.label} must be between ${formatNumber(param.min)} and ${formatNumber(param.max)}`;
  }
  if (param.integer && !Number.isInteger(value)) return `${param.label} must be a whole number`;
  return null;
}

/** Keep only required keys that still exist, at most three. */
export function pruneRequired(required: string[], choices: IndicatorChoice[]): string[] {
  const keys = new Set(choices.map((item) => item.key));
  return required.filter((key) => keys.has(key)).slice(0, MAX_REQUIRED);
}

/** What a saved document becomes, or null when it is not one of ours. */
export function parseSaved(data: Record<string, unknown> | null): {
  choices: IndicatorChoice[];
  mode: CombineMode;
  required: string[];
  conditions: number;
} | null {
  if (!data || !Array.isArray(data['choices'])) return null;
  const choices = (data['choices'] as unknown[]).filter(
    (item): item is IndicatorChoice =>
      typeof item === 'object' &&
      item !== null &&
      typeof (item as IndicatorChoice).key === 'string' &&
      typeof (item as IndicatorChoice).id === 'string' &&
      typeof (item as IndicatorChoice).input === 'string' &&
      typeof (item as IndicatorChoice).params === 'object',
  );
  const mode = data['mode'];
  const conditions = Number(data['conditions']);
  return {
    choices: choices.slice(0, MAX_INDICATORS),
    mode: mode === 'mix' || mode === 'require' ? mode : 'any',
    required: Array.isArray(data['required'])
      ? pruneRequired(
          data['required'].filter((k): k is string => typeof k === 'string'),
          choices,
        )
      : [],
    conditions: conditions >= 1 && conditions <= 3 ? Math.round(conditions) : 3,
  };
}

/** The picker's starting point: what the old fixed chips offered. */
export function defaultChoices(): IndicatorChoice[] {
  return [
    { key: 'i1', id: 'ema', params: { length: 20 }, input: PRICE_INPUT },
    { key: 'i2', id: 'ema', params: { length: 50 }, input: PRICE_INPUT },
    { key: 'i3', id: 'rsi', params: { length: 14 }, input: PRICE_INPUT },
  ];
}
