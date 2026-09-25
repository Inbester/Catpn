"""Period-vs-period comparison and its verdict (SPEC §3.3).

The strategy version is frozen across both periods: the same rules, the
same costs, only the data differs. Anything else would compare two things
at once and explain neither.

The verdict is built from explicit checks rather than a single score, so a
user can see *which* part held up. "Weaker but inside the expected range"
and "outside the range" are different conclusions, and collapsing them into
one number would hide the distinction that matters.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np

from quanta_engine.backtest.types import BacktestResult, Bars
from quanta_engine.forward.montecarlo import (
    DEFAULT_BAND,
    DEFAULT_RUNS,
    Band,
    MonteCarloResult,
    simulate,
    trade_returns_on_equity,
)
from quanta_engine.forward.regime import Regime, describe

MS_PER_DAY = 86_400_000
# A trade count this different suggests the rules fired differently, not
# just that the market moved.
TRADE_COUNT_TOLERANCE = 0.4


class Verdict(StrEnum):
    HOLDS_UP = "holds_up"
    HOLDS_UP_WEAKER = "holds_up_weaker"
    OUTSIDE_RANGE = "outside_range"
    TOO_FEW_TRADES = "too_few_trades"


@dataclass(frozen=True, slots=True)
class Check:
    """One named test behind the verdict."""

    key: str
    label: str
    passed: bool
    # "warn" is a real state: something moved but not enough to fail.
    severity: str  # "ok" | "warn" | "fail"
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "passed": self.passed,
            "severity": self.severity,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class MetricRow:
    """One row of the side-by-side table."""

    key: str
    label: str
    reference: float
    test: float
    unit: str
    # Higher is better for most metrics, but not drawdown or costs.
    higher_is_better: bool
    band: Band | None = None

    @property
    def change(self) -> float:
        return self.test - self.reference

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "reference": self.reference,
            "test": self.test,
            "change": self.change,
            "unit": self.unit,
            "higher_is_better": self.higher_is_better,
            "band": None
            if self.band is None
            else {
                "low": self.band.low,
                "high": self.band.high,
                "median": self.band.median,
                "position": self.band.position(self.test),
                "contains": self.band.contains(self.test),
            },
        }


@dataclass(frozen=True, slots=True)
class PeriodSummary:
    label: str
    start: int
    end: int
    stats: dict[str, Any]
    regime: Regime
    # Cumulative return by trade number, for the chart's x-axis.
    equity_by_trade: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "stats": self.stats,
            "regime": self.regime.to_dict(),
            "equity_by_trade": self.equity_by_trade,
        }


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    verdict: Verdict
    headline: str
    explanation: str
    reading: str
    checks: list[Check]
    metrics: list[MetricRow]
    reference: PeriodSummary
    test: PeriodSummary
    monte_carlo: MonteCarloResult
    strategy_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": str(self.verdict),
            "headline": self.headline,
            "explanation": self.explanation,
            "reading": self.reading,
            "checks": [check.to_dict() for check in self.checks],
            "metrics": [metric.to_dict() for metric in self.metrics],
            "reference": self.reference.to_dict(),
            "test": self.test.to_dict(),
            "strategy_version": self.strategy_version,
            "monte_carlo": {
                "runs": self.monte_carlo.net_percent.runs,
                "confidence": self.monte_carlo.net_percent.confidence,
                "net": {
                    "low": self.monte_carlo.net_percent.low,
                    "high": self.monte_carlo.net_percent.high,
                    "median": self.monte_carlo.net_percent.median,
                },
                "drawdown": {
                    "low": self.monte_carlo.max_drawdown_percent.low,
                    "high": self.monte_carlo.max_drawdown_percent.high,
                    "median": self.monte_carlo.max_drawdown_percent.median,
                },
                "worst_case_equity": self.monte_carlo.worst_case_equity.tolist(),
                "best_case_equity": self.monte_carlo.best_case_equity.tolist(),
                "median_equity": self.monte_carlo.median_equity.tolist(),
            },
        }


def _equity_by_trade(result: BacktestResult, start_equity: float) -> list[float]:
    """Cumulative percentage return after each trade."""
    path = [0.0]
    for trade in result.trades:
        path.append((trade.equity_after - start_equity) / start_equity * 100.0)
    return path


def _longest_drawdown_days(result: BacktestResult) -> float:
    """The longest stretch underwater, in days rather than bars.

    Bars are not comparable across timeframes, and what a trader actually
    sits through is measured in calendar time.
    """
    equity = result.equity
    times = result.equity_time
    if equity.size < 2:
        return 0.0

    peaks = np.maximum.accumulate(equity)
    underwater = equity < peaks

    longest_ms = 0
    run_start: int | None = None
    for index, flag in enumerate(underwater):
        if flag and run_start is None:
            run_start = index
        elif not flag and run_start is not None:
            longest_ms = max(longest_ms, int(times[index]) - int(times[run_start]))
            run_start = None
    if run_start is not None:
        longest_ms = max(longest_ms, int(times[-1]) - int(times[run_start]))

    return longest_ms / MS_PER_DAY


def _build_checks(
    reference: dict[str, Any],
    test: dict[str, Any],
    monte_carlo: MonteCarloResult,
) -> list[Check]:
    checks: list[Check] = []

    net = float(test["net_profit_percent"])
    net_band = monte_carlo.net_percent
    net_in = net_band.contains(net)
    checks.append(
        Check(
            key="net_in_band",
            label="Net in band",
            passed=net_in,
            severity="ok" if net_in else "fail",
            detail=(
                f"{net:+.2f}% against an expected {net_band.low:+.1f}% to {net_band.high:+.1f}%"
            ),
        )
    )

    drawdown = float(test["max_drawdown_percent"])
    dd_band = monte_carlo.max_drawdown_percent
    # Only a drawdown deeper than the band is a problem; a shallower one is
    # good news, so the check is one-sided on purpose.
    dd_ok = drawdown >= dd_band.low
    checks.append(
        Check(
            key="drawdown_in_band",
            label="Drawdown in band",
            passed=dd_ok,
            severity="ok" if dd_ok else "fail",
            detail=(f"{drawdown:.2f}% against a plausible worst of {dd_band.low:.1f}%"),
        )
    )

    reference_trades = int(reference["total_trades"])
    test_trades = int(test["total_trades"])
    if reference_trades == 0:
        similar = False
        ratio = 0.0
    else:
        ratio = test_trades / reference_trades
        similar = abs(ratio - 1.0) <= TRADE_COUNT_TOLERANCE
    checks.append(
        Check(
            key="trade_count",
            label="Trade count similar",
            passed=similar,
            severity="ok" if similar else "warn",
            detail=f"{test_trades} against {reference_trades}",
        )
    )

    reference_pf = reference.get("profit_factor")
    test_pf = test.get("profit_factor")
    if reference_pf is None or test_pf is None:
        pf_severity = "warn"
        pf_detail = "not comparable — a period had no losing trades"
        pf_passed = True
    else:
        # Below 1.0 means the strategy lost money gross; that is a fail
        # whatever the reference was.
        pf_passed = float(test_pf) >= 1.0
        dropped = float(test_pf) < float(reference_pf) * 0.85
        pf_severity = "fail" if not pf_passed else ("warn" if dropped else "ok")
        pf_detail = f"{float(reference_pf):.2f} -> {float(test_pf):.2f}"
    checks.append(
        Check(
            key="profit_factor",
            label="Profit factor",
            passed=pf_passed,
            severity=pf_severity,
            detail=pf_detail,
        )
    )

    return checks


def _decide(checks: list[Check], test_trades: int, reference_trades: int) -> Verdict:
    if test_trades < 5 or reference_trades < 5:
        return Verdict.TOO_FEW_TRADES

    by_key = {check.key: check for check in checks}
    if not by_key["net_in_band"].passed or not by_key["drawdown_in_band"].passed:
        return Verdict.OUTSIDE_RANGE

    weaker = any(check.severity in ("warn", "fail") for check in checks)
    return Verdict.HOLDS_UP_WEAKER if weaker else Verdict.HOLDS_UP


def _write_reading(
    reference: PeriodSummary,
    test: PeriodSummary,
    reference_stats: dict[str, Any],
    test_stats: dict[str, Any],
) -> str:
    """Explain, in words, what changed and what to do about it.

    Generated from the numbers rather than templated at random: the
    sentences name the actual metrics so a user can check the reasoning
    instead of trusting it.
    """
    parts: list[str] = []

    ref_regime = reference.regime
    test_regime = test.regime

    direction = (
        "a steady downtrend"
        if test_regime.return_percent < -2
        else ("a steady uptrend" if test_regime.return_percent > 2 else "a sideways market")
    )
    efficiency_ratio = (
        test_regime.trend_efficiency / ref_regime.trend_efficiency
        if ref_regime.trend_efficiency > 0
        else 0.0
    )
    efficiency_note = (
        f"trend efficiency ~{efficiency_ratio:.0f}x the reference"
        if efficiency_ratio >= 2
        else f"trend efficiency {test_regime.trend_efficiency:.3f} against "
        f"{ref_regime.trend_efficiency:.3f}"
    )
    parts.append(
        f"{test.label} was {direction} ({test_regime.return_percent:+.1f}%, {efficiency_note})."
    )

    long_net = float(test_stats.get("long_net_pnl", 0.0))
    short_net = float(test_stats.get("short_net_pnl", 0.0))
    if long_net != 0.0 or short_net != 0.0:
        if short_net > long_net:
            parts.append(f"Shorts did better ({short_net:+.0f} against {long_net:+.0f} USDT).")
        else:
            parts.append(f"Longs did better ({long_net:+.0f} against {short_net:+.0f} USDT).")
        losing_side = "long" if long_net < 0 else ("short" if short_net < 0 else None)
        if losing_side:
            parts.append(f"The {losing_side} rule kept trading against the move.")

    costs = float(test_stats.get("total_fees", 0.0)) + float(test_stats.get("total_funding", 0.0))
    gross = float(test_stats.get("gross_profit", 0.0))
    if gross > 0 and costs / abs(gross) > 0.5:
        parts.append(
            f"Costs took {costs / abs(gross) * 100:.0f}% of gross profit — "
            "fewer, larger trades would keep more of it."
        )

    parts.append(
        "One period cannot prove a strategy works. Run the same month across "
        "several years, or a walk-forward, for a stronger answer."
    )
    return " ".join(parts)


def compare_periods(
    *,
    reference: BacktestResult,
    reference_bars: Bars,
    reference_label: str,
    test: BacktestResult,
    test_bars: Bars,
    test_label: str,
    initial_capital: float,
    runs: int = DEFAULT_RUNS,
    confidence: float = DEFAULT_BAND,
) -> ComparisonResult:
    """Compare two runs of the same frozen strategy version."""
    if reference.strategy_version != test.strategy_version:
        raise ValueError(
            "A period comparison must use one frozen strategy version; "
            f"got {reference.strategy_version[:12]} and {test.strategy_version[:12]}."
        )

    reference_stats = reference.stats
    test_stats = test.stats

    # Bootstrap the reference's trades into the test's trade count, so the
    # band answers "what could this strategy have done over that many
    # trades" rather than a different-sized sample.
    equity_before = [trade.equity_after - trade.net_pnl for trade in reference.trades]
    returns = trade_returns_on_equity([trade.net_pnl for trade in reference.trades], equity_before)
    monte_carlo = simulate(
        returns,
        trade_count=max(1, int(test_stats["total_trades"])),
        runs=runs,
        confidence=confidence,
    )

    reference_summary = PeriodSummary(
        label=reference_label,
        start=int(reference_bars.time[0]),
        end=int(reference_bars.time[-1]),
        stats=reference_stats,
        regime=describe(
            reference_bars.time, reference_bars.high, reference_bars.low, reference_bars.close
        ),
        equity_by_trade=_equity_by_trade(reference, initial_capital),
    )
    test_summary = PeriodSummary(
        label=test_label,
        start=int(test_bars.time[0]),
        end=int(test_bars.time[-1]),
        stats=test_stats,
        regime=describe(test_bars.time, test_bars.high, test_bars.low, test_bars.close),
        equity_by_trade=_equity_by_trade(test, initial_capital),
    )

    metrics = [
        MetricRow(
            "net_profit",
            "Net profit",
            float(reference_stats["net_profit_percent"]),
            float(test_stats["net_profit_percent"]),
            "%",
            True,
            monte_carlo.net_percent,
        ),
        MetricRow(
            "max_drawdown",
            "Max drawdown",
            float(reference_stats["max_drawdown_percent"]),
            float(test_stats["max_drawdown_percent"]),
            "%",
            True,
            monte_carlo.max_drawdown_percent,
        ),
        MetricRow(
            "longest_drawdown",
            "Longest drawdown",
            _longest_drawdown_days(reference),
            _longest_drawdown_days(test),
            "d",
            False,
        ),
        MetricRow(
            "profit_factor",
            "Profit factor",
            float(reference_stats.get("profit_factor") or 0.0),
            float(test_stats.get("profit_factor") or 0.0),
            "",
            True,
        ),
        MetricRow(
            "win_rate",
            "Win rate",
            float(reference_stats["win_rate_percent"]),
            float(test_stats["win_rate_percent"]),
            "%",
            True,
        ),
        MetricRow(
            "trades",
            "Trades",
            float(reference_stats["total_trades"]),
            float(test_stats["total_trades"]),
            "",
            True,
        ),
        MetricRow(
            "sharpe",
            "Sharpe",
            float(reference_stats.get("sharpe") or 0.0),
            float(test_stats.get("sharpe") or 0.0),
            "",
            True,
        ),
        MetricRow(
            "costs",
            "Costs (fees + funding)",
            -(float(reference_stats["total_fees"]) + float(reference_stats["total_funding"])),
            -(float(test_stats["total_fees"]) + float(test_stats["total_funding"])),
            "",
            True,
        ),
        MetricRow(
            "liquidations",
            "Liquidations",
            float(reference_stats["liquidations"]),
            float(test_stats["liquidations"]),
            "",
            False,
        ),
    ]

    checks = _build_checks(reference_stats, test_stats, monte_carlo)
    verdict = _decide(checks, int(test_stats["total_trades"]), int(reference_stats["total_trades"]))

    net = float(test_stats["net_profit_percent"])
    reference_net = float(reference_stats["net_profit_percent"])
    inside = monte_carlo.net_percent.contains(net)

    headline = (
        f"{test_label} made {net:+.2f}% against {reference_net:+.2f}% in "
        f"{reference_label} — "
        + ("inside the expected range." if inside else "outside the expected range.")
    )
    explanation = (
        f"A single period is noisy: with {int(test_stats['total_trades'])} trades, "
        f"anything from {monte_carlo.net_percent.low:+.1f}% to "
        f"{monte_carlo.net_percent.high:+.1f}% was plausible for this exact strategy."
    )

    return ComparisonResult(
        verdict=verdict,
        headline=headline,
        explanation=explanation,
        reading=_write_reading(reference_summary, test_summary, reference_stats, test_stats),
        checks=checks,
        metrics=metrics,
        reference=reference_summary,
        test=test_summary,
        monte_carlo=monte_carlo,
        strategy_version=test.strategy_version,
    )
