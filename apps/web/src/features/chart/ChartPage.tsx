/**
 * The Chart menu (SPEC §3.1).
 *
 * Drawings, indicators, chart type and scale mode are autosaved per symbol
 * and timeframe through the phase 0 framework, so they survive a reload —
 * which is phase 1's acceptance test.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';

import { Icon } from '@/components/Icon';
import { useAuthStore } from '@/lib/auth/store';
import { loadDocument, saveDocument } from '@/lib/autosave/store';
import { readPalette } from './lib/chartTheme';
import {
  createDrawing,
  drawingScope,
  parseChartDocument,
  type Anchor,
  type Drawing,
  type DrawingTool,
} from './lib/drawings';
import {
  INDICATORS,
  createIndicator,
  defaultIndicators,
  type IndicatorId,
  type IndicatorInstance,
} from './lib/indicatorRegistry';
import { INTERVAL_SECONDS, isInterval, type Bar, type ChartType, type Interval } from './lib/types';
import { barsForRange, type PriceScaleMode, type RangeKey } from './lib/ranges';
import { ChartBottomBar } from './components/ChartBottomBar';
import { ChartCanvas } from './components/ChartCanvas';
import { ChartTopBar } from './components/ChartTopBar';
import { DrawingLayer } from './components/DrawingLayer';
import { DrawingToolbar } from './components/DrawingToolbar';
import { IndicatorsDialog } from './components/IndicatorsDialog';
import { Legend } from './components/Legend';
import { Watchlist } from './components/Watchlist';
import { PriceCountdown } from './components/PriceCountdown';
import { useCountdown } from './hooks/useCountdown';
import { usePaneOffsets } from './hooks/usePaneOffsets';
import { useKlines } from './hooks/useKlines';
import { useTickers } from './hooks/useTickers';
import styles from './ChartPage.module.css';

const DEFAULT_SYMBOL = 'BTCUSDT';
const DEFAULT_INTERVAL: Interval = '15m';

/** Where the active symbol and timeframe are remembered between visits. */
const UI_SCOPE = 'chart';

export function ChartPage() {
  const user = useAuthStore((state) => state.user);

  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [interval, setIntervalValue] = useState<Interval>(DEFAULT_INTERVAL);
  const [chartType, setChartType] = useState<ChartType>('candles');
  const [priceScaleMode, setPriceScaleMode] = useState<PriceScaleMode>('normal');
  const [indicators, setIndicators] = useState<IndicatorInstance[]>(() => defaultIndicators());
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [activeTool, setActiveTool] = useState<DrawingTool>('cursor');
  const [magnet, setMagnet] = useState(false);
  const [selectedDrawing, setSelectedDrawing] = useState<string | null>(null);
  const [hovered, setHovered] = useState<Bar | null>(null);
  const [showIndicators, setShowIndicators] = useState(false);
  const [restored, setRestored] = useState(false);

  // State, not refs: the drawing layer must re-render once these exist.
  const [chart, setChart] = useState<IChartApi | null>(null);
  const [priceSeries, setPriceSeries] = useState<ISeriesApi<
    'Candlestick' | 'Bar' | 'Line' | 'Area'
  > | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  const { bars, loading, error, live, reload } = useKlines(symbol, interval);
  const { tickers } = useTickers();
  const countdown = useCountdown(interval);

  const scope = drawingScope(symbol, interval);
  const timezone = user?.timezone ?? 'UTC';

  // --- Restore the last symbol and timeframe ----------------------------
  useEffect(() => {
    let cancelled = false;

    loadDocument<Record<string, unknown>>('ui', UI_SCOPE)
      .then((data) => {
        if (cancelled || !data) return;
        if (typeof data['symbol'] === 'string') setSymbol(data['symbol']);
        if (typeof data['interval'] === 'string' && isInterval(data['interval'])) {
          setIntervalValue(data['interval']);
        }
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void saveDocument('ui', UI_SCOPE, { symbol, interval });
  }, [symbol, interval]);

  // --- Restore this chart's saved state ----------------------------------
  useEffect(() => {
    let cancelled = false;
    setRestored(false);

    loadDocument<Record<string, unknown>>('chart', scope)
      .then((data) => {
        if (cancelled) return;
        const document = parseChartDocument(data);

        if (document) {
          setDrawings(document.drawings);
          const saved = document.indicators.filter(isIndicatorInstance);
          setIndicators(saved.length > 0 ? saved : defaultIndicators());
          setChartType(document.chartType as ChartType);
          setPriceScaleMode(document.priceScaleMode as PriceScaleMode);
        } else {
          setDrawings([]);
          setIndicators(defaultIndicators());
        }
        setSelectedDrawing(null);
        setRestored(true);
      })
      .catch(() => {
        if (!cancelled) setRestored(true);
      });

    return () => {
      cancelled = true;
    };
  }, [scope]);

  // --- Autosave ----------------------------------------------------------
  useEffect(() => {
    // Skip the first pass after switching charts: writing before the restore
    // completes would overwrite saved drawings with the empty default.
    if (!restored) return;
    void saveDocument('chart', scope, {
      drawings,
      indicators,
      chartType,
      priceScaleMode,
    });
  }, [restored, scope, drawings, indicators, chartType, priceScaleMode]);

  // --- Keyboard ----------------------------------------------------------
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return;

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        searchRef.current?.focus();
        return;
      }

      if (event.altKey) {
        const shortcuts: Record<string, DrawingTool> = {
          t: 'trend',
          h: 'horizontal',
          v: 'vertical',
          j: 'ray',
        };
        const tool = shortcuts[event.key.toLowerCase()];
        if (tool) {
          event.preventDefault();
          setActiveTool(tool);
          return;
        }
      }

      if (event.key === 'Escape') {
        setActiveTool('cursor');
        setSelectedDrawing(null);
        return;
      }

      if ((event.key === 'Delete' || event.key === 'Backspace') && selectedDrawing) {
        event.preventDefault();
        setDrawings((current) => current.filter((d) => d.id !== selectedDrawing));
        setSelectedDrawing(null);
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [selectedDrawing]);

  // --- Handlers ----------------------------------------------------------
  const handleCommit = useCallback(
    (points: Anchor[]) => {
      if (activeTool === 'cursor') return;
      const palette = readPalette();
      setDrawings((current) => [...current, createDrawing(activeTool, points, palette.drawing)]);
      // Stay in the tool so several lines can be drawn in a row.
    },
    [activeTool],
  );

  const handleRange = useCallback(
    (range: RangeKey) => {
      if (!chart) return;
      const count = barsForRange(range, INTERVAL_SECONDS[interval]);
      if (count === null) {
        chart.timeScale().fitContent();
        return;
      }
      const to = bars.length;
      chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, to - count), to });
    },
    [chart, interval, bars.length],
  );

  const allLocked = drawings.length > 0 && drawings.every((d) => d.locked);
  const allHidden = drawings.length > 0 && drawings.every((d) => !d.visible);

  const selected = useMemo(
    () => drawings.find((d) => d.id === selectedDrawing) ?? null,
    [drawings, selectedDrawing],
  );

  // Overlays share the price pane's legend; the rest get their own, placed
  // at the top of the pane the canvas gave them.
  const overlayIndicators = useMemo(
    () => indicators.filter((i) => INDICATORS[i.id]?.overlay),
    [indicators],
  );
  const paneIndicators = useMemo(
    () => indicators.filter((i) => !INDICATORS[i.id]?.overlay),
    [indicators],
  );
  const paneOffsets = usePaneOffsets(chart, paneIndicators.length);

  const lastBar = bars[bars.length - 1] ?? null;

  return (
    <div className={styles.page}>
      <div className={styles.center}>
        <ChartTopBar
          symbol={symbol}
          interval={interval}
          chartType={chartType}
          live={live}
          onOpenSymbolSearch={() => searchRef.current?.focus()}
          onIntervalChange={setIntervalValue}
          onChartTypeChange={setChartType}
          onOpenIndicators={() => {
            setShowIndicators(true);
          }}
          onOpenSettings={() => {
            setShowIndicators(true);
          }}
        />

        <div className={styles.body}>
          <DrawingToolbar
            activeTool={activeTool}
            magnet={magnet}
            allLocked={allLocked}
            allHidden={allHidden}
            drawingCount={drawings.length}
            onSelectTool={setActiveTool}
            onToggleMagnet={() => {
              setMagnet((value) => !value);
            }}
            onToggleLockAll={() => {
              setDrawings((current) => current.map((d) => ({ ...d, locked: !allLocked })));
            }}
            onToggleHideAll={() => {
              setDrawings((current) => current.map((d) => ({ ...d, visible: allHidden })));
            }}
            onRemoveAll={() => {
              setDrawings([]);
              setSelectedDrawing(null);
            }}
          />

          <div className={styles.canvasWrap}>
            <ChartCanvas
              bars={bars}
              chartType={chartType}
              indicators={indicators}
              priceScaleMode={priceScaleMode}
              onCrosshairMove={setHovered}
              onReady={(instance, series) => {
                setChart(instance);
                setPriceSeries(series);
              }}
            />

            <DrawingLayer
              chart={chart}
              series={priceSeries}
              drawings={drawings}
              activeTool={activeTool}
              selectedId={selectedDrawing}
              magnet={magnet}
              bars={bars}
              onCommit={handleCommit}
              onSelect={setSelectedDrawing}
            />

            <Legend
              symbol={symbol}
              interval={interval}
              bars={bars}
              hovered={hovered}
              live={live}
              indicators={overlayIndicators}
              onToggleIndicator={(key) => {
                setIndicators((current) =>
                  current.map((i) => (i.key === key ? { ...i, visible: !i.visible } : i)),
                );
              }}
              onRemoveIndicator={(key) => {
                setIndicators((current) => current.filter((i) => i.key !== key));
              }}
              onConfigureIndicator={() => {
                setShowIndicators(true);
              }}
            />

            {paneIndicators.map((instance, index) => {
              const offset = paneOffsets[index + 1];
              if (offset === undefined) return null;
              return (
                <Legend
                  key={instance.key}
                  variant="pane"
                  offsetTop={offset + 8}
                  symbol={symbol}
                  interval={interval}
                  bars={bars}
                  hovered={hovered}
                  live={live}
                  indicators={[instance]}
                  onToggleIndicator={(key) => {
                    setIndicators((current) =>
                      current.map((i) => (i.key === key ? { ...i, visible: !i.visible } : i)),
                    );
                  }}
                  onRemoveIndicator={(key) => {
                    setIndicators((current) => current.filter((i) => i.key !== key));
                  }}
                  onConfigureIndicator={() => {
                    setShowIndicators(true);
                  }}
                />
              );
            })}

            <PriceCountdown
              chart={chart}
              series={priceSeries}
              lastPrice={lastBar?.close ?? null}
              label={countdown}
              up={lastBar ? lastBar.close >= lastBar.open : true}
            />

            {selected ? (
              <div className={styles.selectionBar} role="toolbar" aria-label="Selected drawing">
                <span className={styles.swatch} style={{ background: selected.color }} />
                <button
                  type="button"
                  className={styles.selectionButton}
                  title={selected.locked ? 'Unlock' : 'Lock'}
                  aria-label={selected.locked ? 'Unlock' : 'Lock'}
                  onClick={() => {
                    setDrawings((current) =>
                      current.map((d) => (d.id === selected.id ? { ...d, locked: !d.locked } : d)),
                    );
                  }}
                >
                  <Icon name={selected.locked ? 'lock' : 'unlock'} size={14} />
                </button>
                <button
                  type="button"
                  className={styles.selectionButton}
                  title="Delete"
                  aria-label="Delete drawing"
                  onClick={() => {
                    setDrawings((current) => current.filter((d) => d.id !== selected.id));
                    setSelectedDrawing(null);
                  }}
                >
                  <Icon name="trash" size={14} />
                </button>
              </div>
            ) : null}

            {loading ? <div className={styles.status}>Loading bars…</div> : null}
            {error ? (
              <div className={styles.status}>
                <div className={styles.error}>
                  {error}
                  <button type="button" className={styles.retry} onClick={reload}>
                    Retry
                  </button>
                </div>
              </div>
            ) : null}
            {!loading && !error && bars.length === 0 ? (
              <div className={styles.status}>
                No bars stored for {symbol} {interval} yet.
              </div>
            ) : null}
          </div>
        </div>

        <ChartBottomBar
          timezone={timezone}
          priceScaleMode={priceScaleMode}
          onRangeSelect={handleRange}
          onPriceScaleModeChange={setPriceScaleMode}
          onResetView={() => chart?.timeScale().scrollToRealTime()}
        />
      </div>

      <Watchlist
        tickers={tickers}
        activeSymbol={symbol}
        onSelect={setSymbol}
        searchRef={searchRef}
      />

      {showIndicators ? (
        <IndicatorsDialog
          onAdd={(id: IndicatorId) => {
            setIndicators((current) => [...current, createIndicator(id)]);
            setShowIndicators(false);
          }}
          onClose={() => {
            setShowIndicators(false);
          }}
        />
      ) : null}
    </div>
  );
}

/** Validate an indicator restored from storage. */
function isIndicatorInstance(value: unknown): value is IndicatorInstance {
  if (typeof value !== 'object' || value === null) return false;
  const instance = value as Record<string, unknown>;
  return (
    typeof instance['key'] === 'string' &&
    typeof instance['id'] === 'string' &&
    typeof instance['params'] === 'object' &&
    instance['params'] !== null
  );
}
