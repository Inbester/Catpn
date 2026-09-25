/**
 * The 48px drawing toolbar (SPEC §2, §3.1).
 *
 * Phase 1 ships the lines group plus the shared state controls: magnet,
 * lock all, hide all and remove all. The Fibonacci, pattern and position
 * groups arrive with the tools that use them.
 */

import { Icon, type IconName } from '@/components/Icon';
import { TOOL_LABELS, TOOL_SHORTCUTS, type DrawingTool } from '../lib/drawings';
import styles from './DrawingToolbar.module.css';

const TOOL_ICONS: Record<DrawingTool, IconName> = {
  cursor: 'cursor',
  trend: 'trendLine',
  ray: 'ray',
  horizontal: 'horizontalLine',
  vertical: 'verticalLine',
  rectangle: 'rectangle',
  fib: 'fib',
  text: 'text',
};

const TOOL_ORDER: DrawingTool[] = [
  'cursor',
  'trend',
  'ray',
  'horizontal',
  'vertical',
  'rectangle',
  'fib',
  'text',
];

export interface DrawingToolbarProps {
  activeTool: DrawingTool;
  magnet: boolean;
  allLocked: boolean;
  allHidden: boolean;
  drawingCount: number;
  onSelectTool: (tool: DrawingTool) => void;
  onToggleMagnet: () => void;
  onToggleLockAll: () => void;
  onToggleHideAll: () => void;
  onRemoveAll: () => void;
}

export function DrawingToolbar({
  activeTool,
  magnet,
  allLocked,
  allHidden,
  drawingCount,
  onSelectTool,
  onToggleMagnet,
  onToggleLockAll,
  onToggleHideAll,
  onRemoveAll,
}: DrawingToolbarProps) {
  return (
    <div className={styles.toolbar} role="toolbar" aria-label="Drawing tools">
      {TOOL_ORDER.map((tool) => {
        const shortcut = TOOL_SHORTCUTS[tool];
        const label = shortcut ? `${TOOL_LABELS[tool]} (${shortcut})` : TOOL_LABELS[tool];
        return (
          <button
            key={tool}
            type="button"
            className={`${styles.tool} ${activeTool === tool ? styles.active : ''}`}
            onClick={() => {
              onSelectTool(tool);
            }}
            title={label}
            aria-label={label}
            aria-pressed={activeTool === tool}
          >
            <Icon name={TOOL_ICONS[tool]} size={18} />
          </button>
        );
      })}

      <div className={styles.divider} />

      <button
        type="button"
        className={`${styles.tool} ${magnet ? styles.on : ''}`}
        onClick={onToggleMagnet}
        title="Magnet — snap to OHLC"
        aria-label="Magnet"
        aria-pressed={magnet}
      >
        <Icon name="magnet" size={18} />
      </button>

      <div className={styles.spacer} />

      <button
        type="button"
        className={`${styles.tool} ${allLocked ? styles.on : ''}`}
        onClick={onToggleLockAll}
        title={allLocked ? 'Unlock all drawings' : 'Lock all drawings'}
        aria-label="Lock all drawings"
        aria-pressed={allLocked}
        disabled={drawingCount === 0}
      >
        <Icon name={allLocked ? 'lock' : 'unlock'} size={18} />
      </button>

      <button
        type="button"
        className={`${styles.tool} ${allHidden ? styles.on : ''}`}
        onClick={onToggleHideAll}
        title={allHidden ? 'Show all drawings' : 'Hide all drawings'}
        aria-label="Hide all drawings"
        aria-pressed={allHidden}
        disabled={drawingCount === 0}
      >
        <Icon name={allHidden ? 'eyeOff' : 'eye'} size={18} />
      </button>

      <button
        type="button"
        className={styles.tool}
        onClick={onRemoveAll}
        title="Remove all drawings"
        aria-label="Remove all drawings"
        disabled={drawingCount === 0}
      >
        <Icon name="trash" size={18} />
      </button>
    </div>
  );
}
