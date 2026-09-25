/**
 * Drawings, rendered on a canvas over the chart.
 *
 * Lightweight Charts has no drawing primitives, so this layer converts each
 * drawing's time/price anchors to pixels through the chart's own scales on
 * every frame. That is what keeps a line pinned to the same bars and prices
 * through zoom, pan and live ticks.
 */

import { useCallback, useEffect, useRef } from 'react';
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts';

import {
  FIB_LEVELS,
  POINTS_REQUIRED,
  type Anchor,
  type Drawing,
  type DrawingTool,
} from '../lib/drawings';
import { readPalette } from '../lib/chartTheme';

export interface DrawingLayerProps {
  chart: IChartApi | null;
  series: ISeriesApi<'Candlestick' | 'Bar' | 'Line' | 'Area'> | null;
  drawings: Drawing[];
  activeTool: DrawingTool;
  selectedId: string | null;
  /** Snap anchors to the nearest OHLC value (SPEC §3.1 magnet). */
  magnet: boolean;
  bars: { time: number; open: number; high: number; low: number; close: number }[];
  onCommit: (points: Anchor[]) => void;
  onSelect: (id: string | null) => void;
}

const HIT_TOLERANCE_PX = 6;

export function DrawingLayer({
  chart,
  series,
  drawings,
  activeTool,
  selectedId,
  magnet,
  bars,
  onCommit,
  onSelect,
}: DrawingLayerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pendingRef = useRef<Anchor[]>([]);
  const cursorRef = useRef<Anchor | null>(null);

  /** Pixel position for a time/price anchor, or null if off-screen. */
  const toPixels = useCallback(
    (anchor: Anchor): { x: number; y: number } | null => {
      if (!chart || !series) return null;
      const x = chart.timeScale().timeToCoordinate((anchor.time / 1000) as Time);
      const y = series.priceToCoordinate(anchor.price);
      if (x === null || y === null) return null;
      return { x, y };
    },
    [chart, series],
  );

  const toAnchor = useCallback(
    (x: number, y: number): Anchor | null => {
      if (!chart || !series) return null;
      const time = chart.timeScale().coordinateToTime(x);
      const price = series.coordinateToPrice(y);
      if (time === null || price === null) return null;

      const anchor: Anchor = { time: Number(time) * 1000, price: Number(price) };
      if (!magnet) return anchor;

      // Snap to whichever of the bar's OHLC values is closest.
      const bar = bars.find((candidate) => candidate.time === anchor.time);
      if (!bar) return anchor;
      const candidates = [bar.open, bar.high, bar.low, bar.close];
      let nearest = candidates[0] as number;
      for (const value of candidates) {
        if (Math.abs(value - anchor.price) < Math.abs(nearest - anchor.price)) nearest = value;
      }
      return { time: anchor.time, price: nearest };
    },
    [chart, series, magnet, bars],
  );

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext('2d');
    if (!context) return;

    const ratio = window.devicePixelRatio || 1;
    const { clientWidth, clientHeight } = canvas;
    if (canvas.width !== clientWidth * ratio || canvas.height !== clientHeight * ratio) {
      canvas.width = clientWidth * ratio;
      canvas.height = clientHeight * ratio;
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, clientWidth, clientHeight);

    const palette = readPalette();

    const paint = (drawing: Drawing, preview = false) => {
      if (!drawing.visible) return;
      const points = drawing.points.map(toPixels);
      if (points.some((point) => point === null)) return;
      const pixels = points as { x: number; y: number }[];

      context.save();
      context.strokeStyle = drawing.color;
      context.fillStyle = drawing.color;
      context.lineWidth = drawing.width;
      context.globalAlpha = preview ? 0.6 : 1;
      if (drawing.style === 'dashed') context.setLineDash([6, 4]);
      if (drawing.style === 'dotted') context.setLineDash([2, 3]);

      const [a, b] = pixels;

      switch (drawing.tool) {
        case 'trend': {
          if (!a || !b) break;
          context.beginPath();
          context.moveTo(a.x, a.y);
          context.lineTo(b.x, b.y);
          context.stroke();
          break;
        }
        case 'ray': {
          if (!a || !b) break;
          // Extend past the right edge, keeping the slope.
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const scale = dx === 0 ? 0 : (clientWidth - a.x) / dx;
          context.beginPath();
          context.moveTo(a.x, a.y);
          context.lineTo(a.x + dx * Math.max(scale, 1), a.y + dy * Math.max(scale, 1));
          context.stroke();
          break;
        }
        case 'horizontal': {
          if (!a) break;
          context.beginPath();
          context.moveTo(0, a.y);
          context.lineTo(clientWidth, a.y);
          context.stroke();
          break;
        }
        case 'vertical': {
          if (!a) break;
          context.beginPath();
          context.moveTo(a.x, 0);
          context.lineTo(a.x, clientHeight);
          context.stroke();
          break;
        }
        case 'rectangle': {
          if (!a || !b) break;
          context.beginPath();
          context.rect(a.x, a.y, b.x - a.x, b.y - a.y);
          context.stroke();
          context.globalAlpha = preview ? 0.08 : 0.12;
          context.fill();
          break;
        }
        case 'fib': {
          if (!a || !b) break;
          context.font = `10px ${palette.fontMono}`;
          context.textBaseline = 'bottom';
          for (const level of FIB_LEVELS) {
            const y = a.y + (b.y - a.y) * level;
            context.beginPath();
            context.moveTo(Math.min(a.x, b.x), y);
            context.lineTo(Math.max(a.x, b.x), y);
            context.stroke();
            context.fillText(`${(level * 100).toFixed(1)}%`, Math.min(a.x, b.x) + 4, y - 2);
          }
          break;
        }
        case 'text': {
          if (!a) break;
          context.font = `12px ${palette.fontMono}`;
          context.textBaseline = 'middle';
          context.fillText(drawing.text ?? 'Text', a.x + 6, a.y);
          break;
        }
      }

      // Selection handles.
      if (drawing.id === selectedId) {
        context.setLineDash([]);
        context.globalAlpha = 1;
        for (const point of pixels) {
          context.beginPath();
          context.arc(point.x, point.y, 4, 0, Math.PI * 2);
          context.fillStyle = palette.bg;
          context.fill();
          context.strokeStyle = drawing.color;
          context.lineWidth = 1.5;
          context.stroke();
        }
      }

      context.restore();
    };

    for (const drawing of drawings) paint(drawing);

    // Rubber-band preview for the drawing in progress.
    const pending = pendingRef.current;
    if (pending.length > 0 && activeTool !== 'cursor' && cursorRef.current) {
      paint(
        {
          id: '__preview',
          tool: activeTool,
          points: [...pending, cursorRef.current],
          color: palette.drawing,
          width: 1,
          style: 'solid',
          locked: false,
          visible: true,
          createdAt: 0,
        },
        true,
      );
    }
  }, [drawings, selectedId, activeTool, toPixels]);

  // Redraw whenever the chart moves or the data changes.
  useEffect(() => {
    if (!chart) return undefined;
    const timeScale = chart.timeScale();

    const redraw = () => {
      draw();
    };
    timeScale.subscribeVisibleLogicalRangeChange(redraw);
    redraw();

    const observer = new ResizeObserver(redraw);
    if (canvasRef.current) observer.observe(canvasRef.current);

    return () => {
      timeScale.unsubscribeVisibleLogicalRangeChange(redraw);
      observer.disconnect();
    };
  }, [chart, draw]);

  useEffect(() => {
    draw();
  }, [draw, bars]);

  /** Distance from a point to a drawing, for hit testing. */
  const distanceTo = useCallback(
    (drawing: Drawing, x: number, y: number): number => {
      const pixels = drawing.points.map(toPixels);
      if (pixels.some((point) => point === null)) return Infinity;
      const [a, b] = pixels as { x: number; y: number }[];
      if (!a) return Infinity;

      if (drawing.tool === 'horizontal') return Math.abs(y - a.y);
      if (drawing.tool === 'vertical') return Math.abs(x - a.x);
      if (drawing.tool === 'text') return Math.hypot(x - a.x, y - a.y);
      if (!b) return Infinity;

      if (drawing.tool === 'rectangle') {
        const insideX = x >= Math.min(a.x, b.x) - 4 && x <= Math.max(a.x, b.x) + 4;
        const insideY = y >= Math.min(a.y, b.y) - 4 && y <= Math.max(a.y, b.y) + 4;
        if (!insideX || !insideY) return Infinity;
        return Math.min(Math.abs(x - a.x), Math.abs(x - b.x), Math.abs(y - a.y), Math.abs(y - b.y));
      }

      // Perpendicular distance to the segment.
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const lengthSquared = dx * dx + dy * dy;
      if (lengthSquared === 0) return Math.hypot(x - a.x, y - a.y);
      const t = Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / lengthSquared));
      return Math.hypot(x - (a.x + t * dx), y - (a.y + t * dy));
    },
    [toPixels],
  );

  const handleClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;

    if (activeTool === 'cursor') {
      // Pick the nearest drawing within tolerance, topmost first.
      let best: { id: string; distance: number } | null = null;
      for (const drawing of drawings) {
        if (!drawing.visible || drawing.locked) continue;
        const distance = distanceTo(drawing, x, y);
        if (distance <= HIT_TOLERANCE_PX && (!best || distance < best.distance)) {
          best = { id: drawing.id, distance };
        }
      }
      onSelect(best?.id ?? null);
      return;
    }

    const anchor = toAnchor(x, y);
    if (!anchor) return;

    pendingRef.current = [...pendingRef.current, anchor];
    const needed = POINTS_REQUIRED[activeTool];

    if (pendingRef.current.length >= needed) {
      onCommit(pendingRef.current);
      pendingRef.current = [];
      cursorRef.current = null;
    }
    draw();
  };

  const handleMove = (event: React.MouseEvent<HTMLCanvasElement>) => {
    if (activeTool === 'cursor' || pendingRef.current.length === 0) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    cursorRef.current = toAnchor(event.clientX - rect.left, event.clientY - rect.top);
    draw();
  };

  return (
    <canvas
      ref={canvasRef}
      onClick={handleClick}
      onMouseMove={handleMove}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        zIndex: 2,
        // Only capture clicks while drawing; otherwise the chart pans.
        pointerEvents: activeTool === 'cursor' ? 'none' : 'auto',
        cursor: activeTool === 'cursor' ? 'default' : 'crosshair',
      }}
    />
  );
}
