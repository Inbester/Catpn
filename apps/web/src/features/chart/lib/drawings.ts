/**
 * Drawing objects and their persistence shape.
 *
 * Drawings are stored per symbol *and* timeframe (SPEC §3.1), anchored to
 * time and price rather than pixels, so they stay put across zoom, pan and
 * a reload — which is the phase 1 acceptance test.
 */

export const DRAWING_TOOLS = [
  'cursor',
  'trend',
  'ray',
  'horizontal',
  'vertical',
  'rectangle',
  'fib',
  'text',
] as const;

export type DrawingTool = (typeof DRAWING_TOOLS)[number];

/** A point anchored in chart space: epoch ms and price. */
export interface Anchor {
  time: number;
  price: number;
}

export interface Drawing {
  id: string;
  tool: Exclude<DrawingTool, 'cursor'>;
  points: Anchor[];
  color: string;
  width: 1 | 2 | 3;
  style: 'solid' | 'dashed' | 'dotted';
  locked: boolean;
  visible: boolean;
  text?: string;
  createdAt: number;
}

/** How many anchors each tool needs before it is complete. */
export const POINTS_REQUIRED: Record<Exclude<DrawingTool, 'cursor'>, number> = {
  trend: 2,
  ray: 2,
  horizontal: 1,
  vertical: 1,
  rectangle: 2,
  fib: 2,
  text: 1,
};

export const TOOL_LABELS: Record<DrawingTool, string> = {
  cursor: 'Cursor',
  trend: 'Trend line',
  ray: 'Ray',
  horizontal: 'Horizontal line',
  vertical: 'Vertical line',
  rectangle: 'Rectangle',
  fib: 'Fibonacci retracement',
  text: 'Text',
};

/** Keyboard shortcuts from the approved design (TradingView's set). */
export const TOOL_SHORTCUTS: Partial<Record<DrawingTool, string>> = {
  trend: 'Alt+T',
  horizontal: 'Alt+H',
  vertical: 'Alt+V',
  ray: 'Alt+J',
};

export const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;

let sequence = 0;

export function createDrawing(
  tool: Exclude<DrawingTool, 'cursor'>,
  points: Anchor[],
  color: string,
): Drawing {
  sequence += 1;
  return {
    id: `d-${Date.now().toString(36)}-${sequence}`,
    tool,
    points,
    color,
    width: 1,
    style: 'solid',
    locked: false,
    visible: true,
    createdAt: Date.now(),
  };
}

/** The autosave scope key for one chart's drawings. */
export function drawingScope(symbol: string, interval: string): string {
  return `${symbol}:${interval}`;
}

export interface ChartDocument extends Record<string, unknown> {
  drawings: Drawing[];
  /** Serialised indicator instances. */
  indicators: unknown[];
  chartType: string;
  priceScaleMode: string;
}

/**
 * Validate a stored document.
 *
 * Local storage can hold anything a previous version wrote, so this checks
 * the shape rather than trusting it — a malformed drawing should be dropped,
 * not crash the chart on load.
 */
export function parseChartDocument(raw: unknown): ChartDocument | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const source = raw as Record<string, unknown>;

  const drawings = Array.isArray(source['drawings']) ? source['drawings'].filter(isDrawing) : [];
  const indicators = Array.isArray(source['indicators']) ? source['indicators'] : [];

  return {
    drawings,
    indicators,
    chartType: typeof source['chartType'] === 'string' ? source['chartType'] : 'candles',
    priceScaleMode:
      typeof source['priceScaleMode'] === 'string' ? source['priceScaleMode'] : 'normal',
  };
}

function isAnchor(value: unknown): value is Anchor {
  if (typeof value !== 'object' || value === null) return false;
  const point = value as Record<string, unknown>;
  return (
    typeof point['time'] === 'number' &&
    Number.isFinite(point['time']) &&
    typeof point['price'] === 'number' &&
    Number.isFinite(point['price'])
  );
}

export function isDrawing(value: unknown): value is Drawing {
  if (typeof value !== 'object' || value === null) return false;
  const drawing = value as Record<string, unknown>;

  if (typeof drawing['id'] !== 'string') return false;
  if (typeof drawing['tool'] !== 'string') return false;
  if (!(drawing['tool'] in POINTS_REQUIRED)) return false;
  if (!Array.isArray(drawing['points'])) return false;
  if (!drawing['points'].every(isAnchor)) return false;

  const required = POINTS_REQUIRED[drawing['tool'] as Exclude<DrawingTool, 'cursor'>];
  return drawing['points'].length === required;
}
