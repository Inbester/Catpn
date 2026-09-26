/**
 * A page for looking at the glossary tip in a real browser.
 *
 * Not part of the app: it is reached only by opening glossary.html, which
 * exists so the dwell, the placement and the Persian rendering can be
 * checked against real layout rather than jsdom's absence of it.
 */

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { GlossaryTip } from '@/features/glossary/GlossaryTip';
import '@/styles/global.css';

function Harness() {
  return (
    <div
      id="scroller"
      style={{ padding: 40, maxWidth: 700, lineHeight: 1.8, height: '100%', overflowY: 'auto' }}
    >
      <h1>Glossary harness</h1>
      <p>
        The maximum drawdown was 12.4% and the profit factor was 1.8, on a walk-forward run with
        leverage at 5x. Watch the funding and the slippage: the risk of ruin is what the win rate
        hides.
      </p>
      <p>
        <input defaultValue="drawdown inside an input" style={{ width: 300 }} /> — nothing should
        appear over a field.
      </p>
      {/* Tall enough to scroll, so the scroll-dismisses check is real. */}
      <div style={{ height: 1200 }} />
      <p id="edge" style={{ position: 'fixed', bottom: 8, left: 24 }}>
        A drawdown at the very bottom edge — the tip should flip above this line.
      </p>
      <p id="corner" style={{ position: 'fixed', bottom: 8, right: 8 }}>
        leverage
      </p>
      <GlossaryTip />
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Harness />
  </StrictMode>,
);
