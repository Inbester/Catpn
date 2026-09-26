import { describe, expect, it } from 'vitest';

import { lookup, normalise, TERMS } from './terms';

describe('normalise', () => {
  it('folds case', () => {
    expect(normalise('Drawdown')).toBe('drawdown');
    expect(normalise('RSI')).toBe('rsi');
  });

  it('strips surrounding punctuation but keeps inner marks', () => {
    expect(normalise('(drawdown),')).toBe('drawdown');
    expect(normalise('"walk-forward"')).toBe('walk-forward');
    expect(normalise('p-value.')).toBe('p-value');
  });

  it('returns empty for a token with no letters', () => {
    expect(normalise('—')).toBe('');
    expect(normalise('')).toBe('');
  });
});

describe('lookup', () => {
  it('finds a single word', () => {
    expect(lookup('leverage')?.fa).toBe(TERMS.leverage?.fa);
  });

  it('ignores words with no entry', () => {
    expect(lookup('the')).toBeNull();
    expect(lookup('quanta')).toBeNull();
  });

  it('prefers the phrase over either word in it', () => {
    // "factor" alone has no entry, but more importantly the phrase means
    // something neither word does.
    const phrase = lookup('profit', '', 'factor');
    expect(phrase).toBe(TERMS['profit factor']);
    expect(lookup('factor', 'profit', '')).toBe(TERMS['profit factor']);
  });

  it('prefers the three-word phrase over the two-word one', () => {
    expect(lookup('of', 'risk', 'ruin')).toBe(TERMS['risk of ruin']);
  });

  it('falls back to the single word when the phrase has no entry', () => {
    expect(lookup('leverage', 'maximum', 'today')).toBe(TERMS.leverage);
  });

  it('matches through punctuation on the neighbours', () => {
    expect(lookup('rate', '(win', ')')).toBe(TERMS['win rate']);
  });

  it('rejects a bare punctuation token', () => {
    expect(lookup('—', 'profit', 'factor')).toBeNull();
  });
});

describe('the glossary itself', () => {
  it('keys are lower case, since lookup folds case', () => {
    for (const key of Object.keys(TERMS)) {
      expect(key).toBe(key.toLowerCase());
    }
  });

  it('every entry has both a translation and an explanation', () => {
    for (const [key, term] of Object.entries(TERMS)) {
      expect(term.fa.trim(), `${key}.fa`).not.toBe('');
      // The explanation is the point of the tip; a bare translation would
      // not be worth the interruption.
      expect(term.explain.trim().length, `${key}.explain`).toBeGreaterThan(20);
    }
  });

  it('is written in Persian, not transliterated', () => {
    for (const [key, term] of Object.entries(TERMS)) {
      expect(/[؀-ۿ]/.test(term.fa), `${key}.fa`).toBe(true);
      expect(/[؀-ۿ]/.test(term.explain), `${key}.explain`).toBe(true);
    }
  });

  it('phrase keys are reachable: lookup only ever joins three words', () => {
    for (const key of Object.keys(TERMS)) {
      expect(key.split(' ').length, key).toBeLessThanOrEqual(3);
    }
  });
});
