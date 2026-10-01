"""Running a Discover search as a job (SPEC §3.2)."""

from __future__ import annotations

from typing import Any

import structlog
from quanta_engine.backtest.types import Bars
from quanta_engine.discover.catalog import Built, CatalogError, Choice, build
from quanta_engine.discover.primitives import build_primitives
from quanta_engine.discover.rules import count_raw_combinations, count_rules
from quanta_engine.discover.search import SearchConfig, run_search
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.exchanges.base import Interval
from quanta.services import market_store
from quanta.services.backtest_service import BacktestError, to_bars
from quanta.services.jobs import Job, progress_reporter

logger = structlog.get_logger(__name__)

MAX_BARS = 200_000
MIN_BARS = 200

# The most rules one search may test (each is tried 8 ways). Half a million
# tests run in about half a minute; this allows a few minutes, and a choice
# that would go past it is refused with the size, before anything runs.
MAX_RULES = 250_000


def build_series(
    choices: list[dict[str, Any]], bars: Bars, *, require: list[str] | None = None
) -> Built:
    """The series for the chosen indicators, with request errors made readable."""
    try:
        built = build(
            [
                Choice(
                    key=str(item["key"]),
                    id=str(item["id"]),
                    params=dict(item.get("params") or {}),
                    input=str(item.get("input") or "close"),
                )
                for item in choices
            ],
            bars,
        )
    except CatalogError as exc:
        raise BacktestError(str(exc)) from exc
    missing = [key for key in require or [] if key not in built.labels]
    if missing:
        raise BacktestError(f"A required indicator ({missing[0]}) is not among the chosen ones.")
    return built


async def load_bars(
    db: AsyncSession, symbol: str, interval: str, start: int | None, end: int | None
) -> Bars:
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
    return to_bars(rows)


def plan(
    choices: list[dict[str, Any]],
    bars: Bars,
    *,
    mix_indicators: bool,
    require: list[str] | None = None,
    max_conditions: int = 3,
) -> dict[str, Any]:
    """What a search would cost, without running it.

    Shown before the button is pressed, because "this will run 558,624
    tests" is the difference between a considered click and a surprise.
    """
    built = build_series(choices, bars, require=require)
    primitives = build_primitives(built.series)
    triggers = sum(1 for p in primitives if p.is_trigger)
    rules = count_rules(
        primitives,
        max_filters=max_conditions - 1,
        mix_indicators=mix_indicators,
        require=frozenset(require or []),
        limit=MAX_RULES,
    )
    too_large = rules > MAX_RULES
    return {
        "series": [
            {"key": s.key, "label": s.label, "scale": s.scale, "source": s.source.key}
            for s in built.series
        ],
        "labels": built.labels,
        "primitives": len(primitives),
        "filters": len(primitives) - triggers,
        "triggers": triggers,
        "raw_combinations": count_raw_combinations(primitives, max_size=max_conditions),
        # Past the cap the exact figure is not worth computing; the flag
        # and the cap say what the user needs to know.
        "rules": min(rules, MAX_RULES),
        "tests": min(rules, MAX_RULES) * 8,
        "too_large": too_large,
        "max_rules": MAX_RULES,
    }


def search_work(
    *,
    choices: list[dict[str, Any]],
    bars: Bars,
    cost_percent: float,
    mix_indicators: bool,
    require: list[str],
    max_conditions: int,
    max_hits: int,
) -> Any:
    """The callable the job runs. Pure: no session, no request state."""

    def work(job: Job) -> dict[str, Any]:
        built = build_series(choices, bars, require=require)
        result = run_search(
            built.series,
            built.data,
            bars.close,
            config=SearchConfig(
                cost_percent=cost_percent,
                mix_indicators=mix_indicators,
                max_filters=max_conditions - 1,
                require=frozenset(require),
            ),
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
                    "rule_label": hit.rule_label,
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
