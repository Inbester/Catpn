/**
 * Persian help on hover.
 *
 * The interface is English. Rest the pointer on a word for a moment and
 * its Persian translation and an explanation appear underneath it.
 *
 * Every decision here is about not being in the way:
 *
 * - It waits. A tip that appears the instant the pointer crosses a word
 *   would flash constantly while someone reads or reaches for a button.
 * - It ignores fields. Nothing appears over an input, a textarea or a
 *   select, where a floating box would cover what is being typed.
 * - It cannot be clicked. `pointer-events: none` means the tip is never
 *   a target and never intercepts anything underneath it.
 * - It leaves on any intent. A move to another word, a scroll, a key, a
 *   click, or the window losing focus all dismiss it at once.
 * - It sits under the *word*, not the cursor, so it never lands beneath
 *   the pointer and blocks the thing being pointed at.
 * - It stays on screen: it flips above the word when there is no room
 *   below, rather than running off the bottom edge.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { lookup, type Term } from './lib/terms';
import { wordAt } from './lib/wordAt';
import styles from './GlossaryTip.module.css';

/**
 * How long the pointer has to rest before the tip appears.
 *
 * Longer than a normal tooltip on purpose. At the usual half second this
 * would fire constantly while someone reads or reaches across the screen,
 * which is exactly what it must not do. At this length it takes a
 * deliberate hold, and a pause to think does not summon it.
 */
const DWELL_MS = 1800;
/** How far it may drift in that time and still count as resting. */
const DRIFT_PX = 4;
const GAP_PX = 8;
const MAX_WIDTH = 320;

interface Shown {
  term: Term;
  word: string;
  /** Where the word is, in viewport coordinates. */
  left: number;
  top: number;
  bottom: number;
}

interface Placed {
  x: number;
  y: number;
}

export function GlossaryTip() {
  const [shown, setShown] = useState<Shown | null>(null);
  const [placed, setPlaced] = useState<Placed | null>(null);
  const tip = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const last = useRef({ x: 0, y: 0 });

  const cancel = useCallback(() => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    setShown(null);
    setPlaced(null);
  }, []);

  // Placed from the rendered size rather than an assumed one: the
  // explanations differ in length, so the height is only known once the
  // text has wrapped. A layout effect runs before the browser paints, so
  // the tip is never seen in the provisional position.
  useLayoutEffect(() => {
    const element = tip.current;
    if (!shown || !element) return;

    const { width, height } = element.getBoundingClientRect();
    const x = Math.max(GAP_PX, Math.min(shown.left, window.innerWidth - width - GAP_PX));
    const below = shown.bottom + GAP_PX;
    // Below the word by default. Above it near the bottom edge, where
    // below would put half the tip off screen.
    const y =
      below + height + GAP_PX <= window.innerHeight
        ? below
        : Math.max(GAP_PX, shown.top - GAP_PX - height);
    setPlaced({ x, y });
  }, [shown]);

  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      // A real move, not the jitter of a resting hand.
      const moved =
        Math.abs(event.clientX - last.current.x) > DRIFT_PX ||
        Math.abs(event.clientY - last.current.y) > DRIFT_PX;
      if (!moved) return;
      last.current = { x: event.clientX, y: event.clientY };

      cancel();
      if (event.pointerType !== 'mouse') return;

      const { clientX, clientY } = event;
      timer.current = setTimeout(() => {
        const hit = wordAt(clientX, clientY);
        if (!hit) return;
        const term = lookup(hit.word, hit.before, hit.after);
        if (!term) return;

        // Anchored to the word so the tip never sits under the pointer.
        setShown({
          term,
          word: hit.word,
          left: hit.rect.left,
          top: hit.rect.top,
          bottom: hit.rect.bottom,
        });
      }, DWELL_MS);
    };

    // Anything that signals intent takes the tip away immediately.
    document.addEventListener('pointermove', onMove, { passive: true });
    document.addEventListener('pointerdown', cancel, { passive: true });
    document.addEventListener('keydown', cancel);
    document.addEventListener('scroll', cancel, { passive: true, capture: true });
    window.addEventListener('blur', cancel);

    return () => {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerdown', cancel);
      document.removeEventListener('keydown', cancel);
      document.removeEventListener('scroll', cancel, { capture: true });
      window.removeEventListener('blur', cancel);
      if (timer.current !== null) clearTimeout(timer.current);
    };
  }, [cancel]);

  if (!shown) return null;

  // Portalled to the body: a tip inside a panel would be clipped by that
  // panel's overflow, which is where most of these words live.
  return createPortal(
    <div
      ref={tip}
      className={styles.tip}
      style={{
        insetInlineStart: placed?.x ?? shown.left,
        top: placed?.y ?? shown.bottom + GAP_PX,
        maxWidth: MAX_WIDTH,
        // Belt and braces for the one frame before it is measured.
        visibility: placed ? 'visible' : 'hidden',
      }}
      // Not a live region: it must not interrupt a screen reader mid-sentence.
      role="tooltip"
      aria-hidden="true"
      data-no-glossary=""
    >
      <div className={styles.head}>
        <span className={styles.word}>{shown.word}</span>
        <span className={styles.fa} dir="rtl">
          {shown.term.fa}
        </span>
      </div>
      <p className={styles.explain} dir="rtl">
        {shown.term.explain}
      </p>
    </div>,
    document.body,
  );
}
