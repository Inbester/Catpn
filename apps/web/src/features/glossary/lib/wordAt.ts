/**
 * The word under a point on screen.
 *
 * Nothing in the app is annotated for this. Wrapping every term in a
 * component would mean touching every page and still missing the ones
 * written later, so the word is read from the document at the pointer
 * instead — any English word anywhere becomes hoverable for free.
 */

export interface WordHit {
  word: string;
  before: string;
  after: string;
  /** The word's box, so the tip can sit under the word rather than the cursor. */
  rect: DOMRect;
}

/** Elements where a tip would be in the way rather than helpful. */
function isBusy(node: Node | null): boolean {
  let element = node instanceof Element ? node : node?.parentElement;
  while (element) {
    const tag = element.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (element instanceof HTMLElement && element.isContentEditable) return true;
    // The tip itself, and anything that opted out.
    if (element.hasAttribute('data-no-glossary')) return true;
    element = element.parentElement;
  }
  return false;
}

interface CaretHit {
  node: Node;
  offset: number;
}

/** caretPositionFromPoint, with the WebKit-only spelling as a fallback. */
function caretAt(x: number, y: number): CaretHit | null {
  const doc = document as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
  };

  if (typeof doc.caretPositionFromPoint === 'function') {
    const position = doc.caretPositionFromPoint(x, y);
    return position ? { node: position.offsetNode, offset: position.offset } : null;
  }
  if (typeof doc.caretRangeFromPoint === 'function') {
    const range = doc.caretRangeFromPoint(x, y);
    return range ? { node: range.startContainer, offset: range.startOffset } : null;
  }
  return null;
}

const WORD_CHAR = /[\p{L}\p{N}'’-]/u;

function boundsAround(text: string, offset: number): [number, number] | null {
  if (offset < 0 || offset > text.length) return null;

  let start = offset;
  let end = offset;
  // The caret can land just past the word, so step back one when it does.
  if (start > 0 && !WORD_CHAR.test(text[start] ?? '')) start -= 1;
  if (!WORD_CHAR.test(text[start] ?? '')) return null;

  while (start > 0 && WORD_CHAR.test(text[start - 1] ?? '')) start -= 1;
  end = start;
  while (end < text.length && WORD_CHAR.test(text[end] ?? '')) end += 1;
  return end > start ? [start, end] : null;
}

/** The word at a viewport point, with its neighbours and its box. */
export function wordAt(x: number, y: number): WordHit | null {
  const caret = caretAt(x, y);
  if (!caret || caret.node.nodeType !== Node.TEXT_NODE) return null;
  if (isBusy(caret.node)) return null;

  const text = caret.node.textContent ?? '';
  const bounds = boundsAround(text, caret.offset);
  if (!bounds) return null;
  const [start, end] = bounds;

  const range = document.createRange();
  range.setStart(caret.node, start);
  range.setEnd(caret.node, end);
  const rect = range.getBoundingClientRect();
  range.detach();

  // The pointer has to actually be over the word, not merely on the line
  // next to it — otherwise a tip appears while reading past the end.
  if (x < rect.left - 2 || x > rect.right + 2 || y < rect.top - 2 || y > rect.bottom + 2) {
    return null;
  }

  const before = boundsAround(text, Math.max(0, start - 2));
  const after = boundsAround(text, Math.min(text.length, end + 1));

  return {
    word: text.slice(start, end),
    before: before && before[1] <= start ? text.slice(before[0], before[1]) : '',
    after: after && after[0] >= end ? text.slice(after[0], after[1]) : '',
    rect,
  };
}
