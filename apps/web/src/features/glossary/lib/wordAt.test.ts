import { afterEach, describe, expect, it } from 'vitest';

import { wordAt } from './wordAt';

/**
 * jsdom implements neither caret-from-point API and has no layout at all,
 * so Range.getBoundingClientRect does not exist on its prototype either.
 * Both are stubbed. What is under test is the word-boundary walk and the
 * guard that the pointer is really over the word — the two places a real
 * browser would not save us.
 */

const RECT = { left: 100, right: 160, top: 40, bottom: 56 };

function mount(html: string): Text {
  document.body.innerHTML = html;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const text = walker.nextNode();
  if (!(text instanceof Text)) throw new Error('no text node');
  return text;
}

/** Point the caret at `offset` in `node`, and give every range one box. */
function caretAt(node: Text, offset: number, rect = RECT) {
  (document as unknown as Record<string, unknown>).caretPositionFromPoint = () => ({
    offsetNode: node,
    offset,
  });
  // Assigned rather than spied on: jsdom has no layout, so the method is
  // absent from the prototype and there is nothing to spy on.
  Range.prototype.getBoundingClientRect = () => ({
    ...rect,
    width: rect.right - rect.left,
    height: rect.bottom - rect.top,
    x: rect.left,
    y: rect.top,
    toJSON: () => ({}),
  });
}

/** A point comfortably inside RECT. */
const INSIDE: [number, number] = [120, 48];

afterEach(() => {
  delete (Range.prototype as Partial<Range>).getBoundingClientRect;
  delete (document as unknown as Record<string, unknown>).caretPositionFromPoint;
  document.body.innerHTML = '';
});

describe('wordAt', () => {
  it('reads the word around the caret', () => {
    const node = mount('<p>maximum drawdown limit</p>');
    caretAt(node, 10); // inside "drawdown"
    expect(wordAt(...INSIDE)?.word).toBe('drawdown');
  });

  it('gives the neighbouring words, for phrase lookup', () => {
    const node = mount('<p>maximum drawdown limit</p>');
    caretAt(node, 10);
    const hit = wordAt(...INSIDE);
    expect(hit?.before).toBe('maximum');
    expect(hit?.after).toBe('limit');
  });

  it('leaves the neighbours empty at the ends of a line', () => {
    const node = mount('<p>drawdown</p>');
    caretAt(node, 3);
    const hit = wordAt(...INSIDE);
    expect(hit?.before).toBe('');
    expect(hit?.after).toBe('');
  });

  it('steps back when the caret lands just past a word', () => {
    const node = mount('<p>drawdown limit</p>');
    caretAt(node, 8); // on the space
    expect(wordAt(...INSIDE)?.word).toBe('drawdown');
  });

  it('keeps hyphens inside a word', () => {
    const node = mount('<p>walk-forward analysis</p>');
    caretAt(node, 3);
    expect(wordAt(...INSIDE)?.word).toBe('walk-forward');
  });

  it('is silent when the pointer is past the end of the line', () => {
    const node = mount('<p>drawdown</p>');
    caretAt(node, 3);
    // Same line, well to the right of the word's box.
    expect(wordAt(400, 48)).toBeNull();
  });

  it('is silent over a text input, where a tip would cover the typing', () => {
    document.body.innerHTML = '<label>drawdown<input value="x" /></label>';
    const input = document.querySelector('input');
    const label = document.querySelector('label');
    const node = label?.firstChild;
    if (!(node instanceof Text) || !input) throw new Error('setup');
    // The caret resolves into the input's subtree.
    input.append('drawdown');
    caretAt(input.firstChild as Text, 3);
    expect(wordAt(...INSIDE)).toBeNull();
  });

  it('is silent inside anything marked data-no-glossary', () => {
    const node = mount('<p data-no-glossary="">drawdown</p>');
    caretAt(node, 3);
    expect(wordAt(...INSIDE)).toBeNull();
  });

  it('is silent when no caret API answers', () => {
    mount('<p>drawdown</p>');
    delete (document as unknown as Record<string, unknown>).caretPositionFromPoint;
    expect(wordAt(...INSIDE)).toBeNull();
  });
});
