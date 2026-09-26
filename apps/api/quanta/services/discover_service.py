"""Running a Discover search as a job (SPEC §3.2)."""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog
from quanta_engine.discover.primitives import Series, Source, build_primitives
from quanta_engine.discover.rules import count_raw_combinations, enumerate_rules
from quanta_engine.discover.search import SearchConfig, run_search
from quanta_engine.series import ema, rsi, sma
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.exchanges.base import Interval
from quanta.services import market_store
from quanta.services.backtest_service import BacktestError, to_bars
from quanta.services.jobs import Job, progress_reporter

logger = structlog.get_logger(__name__)

MAX_BARS = 200_000
MIN_BARS = 200

# The indicator chips a search can be built from. Each one publishes its
# series and the scale they live on; the enumerator needs nothing else.
# Adding a chip here is the only change a new source requires.
SOURCE_LIBRARY: dict[str, dict[str, Any]] = {
    "price": {"label": "Price", "is_price": True, "lines": [("close", "Price", "price")]},
    "ema": {
        "label": "EMA 20/50",
        "lines": [("ema20", "EMA 20", "price"), ("ema50", "EMA 50", "price")],
    },
    "sma": {
        "label": "SMA 50/200",
        "lines": [("sma50", "SMA 50", "price"), ("sma200", "SMA 200", "price")],
    },
    "rsi": {"label": "RSI 14", "lines": [("rsi14", "RSI 14", "bounded_100")]},
    "macd": {
        "label": "MACD",
        "lines": [
            ("macd", "MACD", "centered_0"),
            ("macd_signal", "MACD signal", "centered_0"),
        ],
    },
}


def _compute(key: str, close: np.ndarray) -> dict[str, np.ndarray]:
    if key == "price":
        return {"close": close}
    if key == "ema":
        return {"ema20": ema(close, 20), "ema50": ema(close, 50)}
    if key == "sma":
        return {"sma50": sma(close, 50), "sma200": sma(close, 200)}
    if key == "rsi":
        return {"rsi14": rsi(close, 14)}
    if key == "macd":
        fast, slow = ema(close, 12), ema(close, 26)
        line = fast - slow
        return {"macd": line, "macd_signal": ema(line, 9)}
    raise BacktestError(f"Unknown source {key!r}.")


def build_series(source_keys: list[str], close: np.ndarray) -> tuple[list[Series], dict[str, Any]]:
    """The series and their data for the chosen chips.

    Price is always included: divergence is defined against it, and a
    search with no price has no returns to explain.
    """
    keys = ["price", *[k for k in source_keys if k != "price"]]
    unknown = [k for k in keys if k not in SOURCE_LIBRARY]
    if unknown:
        raise BacktestError(f"Unknown source(s): {', '.join(unknown)}.")

    series: list[Series] = []
    data: dict[str, Any] = {}
    for key in keys:
        entry = SOURCE_LIBRARY[key]
        source = Source(key=key, label=str(entry["label"]), is_price=bool(entry.get("is_price")))
        data.update(_compute(key, close))
        for line_key, line_label, scale in entry["lines"]:
            series.append(Series(line_key, line_label, source, scale))  # type: ignore[arg-type]
    return series, data


async def load_close(
    db: AsyncSession, symbol: str, interval: str, start: int | None, end: int | None
) -> np.ndarray:
    try:
        parsed = Interval(interval)
    except ValueError as exc:
        raise BacktestError(f"Unsupported interval {interval!r}.") from exc

    rows = await market_store.read_bars(db, symbol, parsed, start=start, end=end, limit=MAX_BARS)
    if len(rows) < MIN_BARS:
        raise BacktestError(
            f"A search needs at least {MIN_BARS} bars; {symbol} {interval} has "
            f"{len(rows)}. Load more history first."
        )
    return to_bars(rows).close


def plan(source_keys: list[str], close: np.ndarray, *, mix_indicators: bool) -> dict[str, Any]:
    """What a search would cost, without running it.

    Shown before the button is pressed, because "this will run 558,624
    tests" is the difference between a considered click and a surprise.
    """
    series, _ = build_series(source_keys, close)
    primitives = build_primitives(series)
    triggers = sum(1 for p in primitives if p.is_trigger)
    rules = sum(1 for _ in enumerate_rules(primitives, mix_indicators=mix_indicators))
    return {
        "series": [
            {"key": s.key, "label": s.label, "scale": s.scale, "source": s.source.key}
            for s in series
        ],
        "primitives": len(primitives),
        "filters": len(primitives) - triggers,
        "triggers": triggers,
        "raw_combinations": count_raw_combinations(primitives),
        "rules": rules,
        "tests": rules * 8,
    }


def search_work(
    *,
    source_keys: list[str],
    close: np.ndarray,
    cost_percent: float,
    mix_indicators: bool,
    max_hits: int,
) -> Any:
    """The callable the job runs. Pure: no session, no request state."""

    def work(job: Job) -> dict[str, Any]:
        series, data = build_series(source_keys, close)
        result = run_search(
            series,
            data,
            close,
            config=SearchConfig(cost_percent=cost_percent, mix_indicators=mix_indicators),
            progress=progress_reporter(job),
        )
        return {
            "tested": result.tested,
            "significant_uncorrected": result.significant_uncorrected,
            "expected_false_hits": result.expected_false_hits,
            "threshold_p": result.threshold_p,
            "in_sample_bars": result.in_sample_bars,
            "out_of_sample_bars": result.out_of_sample_bars,
            "hits": [
                {
                    "rule_key": hit.rule_key,
                    "side": hit.side,
                    "horizon": hit.horizon,
                    "signals": hit.signals,
                    "mean_return_percent": hit.mean_return_percent,
                    "mean_net_percent": hit.mean_net_percent,
                    "t_statistic": hit.t_statistic,
                    "p_value": hit.p_value,
                    "win_rate": hit.win_rate,
                    "out_of_sample_mean_percent": hit.out_of_sample_mean_percent,
                    "out_of_sample_signals": hit.out_of_sample_signals,
                }
                for hit in result.hits[:max_hits]
            ],
            "hits_total": len(result.hits),
        }

    return work
