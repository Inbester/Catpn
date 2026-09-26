"""Robustness: would this still work if the world were slightly different?

A backtest is one path through one history. These tests ask what happens
when that path is disturbed — the parameters shifted, the trades
reshuffled, the costs raised, the best trades taken away. A strategy that
survives all of them is not proven; one that fails any of them is refuted
cheaply, which is the point.

Every test here is built to be *unflattering*. The stress cases only make
things worse, the trade shuffle keeps the real tail, and the parameter
surface reports the plateau rather than the peak — because a peak is
usually the shape of an overfit.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray

from quanta_engine.backtest.engine import run_backtest
from quanta_engine.backtest.types import BacktestConfig, Bars, FundingEvent
from quanta_engine.strategy import Strategy

Array = NDArray[np.float64]

# A year of 8-hourly settlements, for the funding stress case.
SETTLEMENTS_PER_YEAR = 365 * 3


@dataclass(frozen=True, slots=True)
class StressCase:
    name: str
    description: str
    net_percent: float
    max_drawdown_percent: float
    trades: int
    # Change against the base run, in points of return.
    delta_percent: float
    survived: bool
    # Whether the case is meant to be harder than the base. Four of the
    # five are; the VIP3 tier is cheaper than VIP0, so it is a what-if
    # about qualifying for it, not a test of survival. Presenting a fee
    # discount as a stress case would let a strategy "pass" by getting
    # a benefit it has not earned.
    adverse: bool = True


@dataclass(frozen=True, slots=True)
class RiskMeasures:
    """Daily tail risk and position sizing."""

    var_95_percent: float
    cvar_95_percent: float
    kelly_fraction: float
    half_kelly_fraction: float


@dataclass(frozen=True, slots=True)
class ParameterPoint:
    params: dict[str, float]
    net_percent: float
    max_drawdown_percent: float
    trades: int


@dataclass(frozen=True, slots=True)
class ParameterSurface:
    points: list[ParameterPoint]
    best: ParameterPoint | None
    # The best point's neighbours, averaged. A peak that its neighbours do
    # not support is a fitting artefact, not a setting.
    neighbourhood_mean_percent: float
    plateau: bool


def value_at_risk(returns: Array, confidence: float = 0.95) -> tuple[float, float]:
    """VaR and CVaR at ``confidence``, as negative percents.

    VaR is the loss the worst 5% of periods start at; CVaR is the average
    of those periods. CVaR is the one that matters — VaR says where the
    tail begins and says nothing about how far it goes.
    """
    if returns.size == 0:
        return 0.0, 0.0
    cut = float(np.percentile(returns, (1.0 - confidence) * 100.0))
    tail = returns[returns <= cut]
    cvar = float(np.mean(tail)) if tail.size else cut
    return cut, cvar


def kelly_fraction(returns: Array) -> float:
    """The Kelly stake for these per-trade returns.

    Kelly maximises long-run growth and is famously too aggressive to
    trade: it assumes the distribution is known exactly, and a small error
    in the estimate is punished by a large drawdown. It is reported so the
    half-Kelly beside it has a reference, not as a recommendation.
    """
    if returns.size < 2:
        return 0.0
    mean = float(np.mean(returns))
    variance = float(np.var(returns, ddof=1))
    if variance <= 0:
        return 0.0
    return max(0.0, mean / variance)


def risk_measures(trade_returns: Array) -> RiskMeasures:
    var, cvar = value_at_risk(trade_returns)
    kelly = kelly_fraction(trade_returns)
    return RiskMeasures(
        var_95_percent=var * 100.0,
        cvar_95_percent=cvar * 100.0,
        kelly_fraction=kelly,
        half_kelly_fraction=kelly / 2.0,
    )


def reshuffled_years(
    trade_returns: Array,
    *,
    trades_per_year: int,
    runs: int = 1_000,
    seed: int = 20260926,
) -> dict[str, float]:
    """A thousand years built from the same trades in a different order.

    Order is the one thing a backtest cannot claim to have got right: the
    same trades arriving differently produce very different drawdowns, and
    the worst orderings are the ones that end an account. Sampling with
    replacement keeps the real distribution of trade sizes, tail included.
    """
    if trade_returns.size == 0 or trades_per_year < 1:
        return {"median_percent": 0.0, "p5_percent": 0.0, "p95_percent": 0.0, "ruin_rate": 0.0}

    rng = np.random.default_rng(seed)
    draws = rng.integers(0, trade_returns.size, size=(runs, trades_per_year))
    paths = np.cumprod(1.0 + trade_returns[draws], axis=1)
    finals = (paths[:, -1] - 1.0) * 100.0
    peaks = np.maximum.accumulate(paths, axis=1)
    worst = np.min((paths - peaks) / peaks, axis=1) * 100.0

    return {
        "median_percent": float(np.median(finals)),
        "p5_percent": float(np.percentile(finals, 5)),
        "p95_percent": float(np.percentile(finals, 95)),
        # A path that lost half is one most people would have stopped.
        "ruin_rate": float(np.mean(worst <= -50.0) * 100.0),
    }


def _run(
    strategy: Strategy,
    bars: Bars,
    config: BacktestConfig,
    funding: list[FundingEvent] | None,
) -> tuple[float, float, int]:
    result = run_backtest(strategy, bars, config, funding=funding)
    return (
        float(result.stats["net_profit_percent"]),
        float(result.stats["max_drawdown_percent"]),
        int(result.stats["total_trades"]),
    )


def stress_tests(
    strategy: Strategy,
    bars: Bars,
    *,
    config: BacktestConfig | None = None,
    funding: list[FundingEvent] | None = None,
) -> list[StressCase]:
    """The five cases SPEC §3.2 names.

    Four are adverse and are asserted never to help. The fifth, VIP3 fees,
    is cheaper than the VIP0 default, so it is a what-if about qualifying
    for that tier rather than a test of survival — it is marked as such so
    a fee discount is never read as a strategy passing something.

    "Survived" means the case still made money. It is a low bar on
    purpose: a strategy that only works at VIP0 fees with no slippage is
    not a strategy, it is a rounding error with a chart.
    """
    config = config or BacktestConfig()
    base_net, _, _ = _run(strategy, bars, config, funding)

    cases: list[tuple[str, str, BacktestConfig, list[FundingEvent] | None, bool]] = [
        (
            "VIP3 fees",
            "Maker 0.016%, taker 0.04%. Cheaper than VIP0, so this is what "
            "the strategy would earn on a tier it has not reached yet.",
            replace(config, maker_fee=0.00016, taker_fee=0.0004),
            funding,
            False,
        ),
        (
            "Fees doubled",
            "Twice the fee schedule, for a venue change or a tier loss.",
            replace(config, maker_fee=config.maker_fee * 2, taker_fee=config.taker_fee * 2),
            funding,
            True,
        ),
        (
            "Slippage tripled",
            "Thin books, or an order larger than the top of the book.",
            replace(config, slippage_bps=config.slippage_bps * 3),
            funding,
            True,
        ),
        (
            "Funding +0.03% per 8h",
            "A persistently crowded side of the trade.",
            config,
            _worsen_funding(funding, 0.0003),
            True,
        ),
    ]

    out: list[StressCase] = []
    for name, description, trial, trial_funding, adverse in cases:
        net, drawdown, trades = _run(strategy, bars, trial, trial_funding)
        out.append(
            StressCase(
                name=name,
                description=description,
                net_percent=net,
                max_drawdown_percent=drawdown,
                trades=trades,
                delta_percent=net - base_net,
                survived=net > 0,
                adverse=adverse,
            )
        )

    out.append(_without_best_trades(strategy, bars, config, funding, count=5))
    return out


def _worsen_funding(funding: list[FundingEvent] | None, extra: float) -> list[FundingEvent] | None:
    """Push every settlement against the position by ``extra``.

    Adding the same signed amount would help shorts as much as it hurt
    longs. A stress case that helps is not a stress case, so the rate is
    moved away from zero in whichever direction it already points.
    """
    if not funding:
        return funding
    return [
        replace(event, rate=event.rate + (extra if event.rate >= 0 else -extra))
        for event in funding
    ]


def _without_best_trades(
    strategy: Strategy,
    bars: Bars,
    config: BacktestConfig,
    funding: list[FundingEvent] | None,
    *,
    count: int,
) -> StressCase:
    """What the run becomes with its best trades removed.

    Not a re-run: removing a trade from the middle would change every
    position afterwards. The result is recomputed from the trade list, so
    it answers exactly the question asked — how much of the return came
    from a handful of trades — rather than a different backtest.
    """
    result = run_backtest(strategy, bars, config, funding=funding)
    if not result.trades:
        return StressCase(
            name=f"Best {count} trades removed",
            description="No trades to remove.",
            net_percent=0.0,
            max_drawdown_percent=0.0,
            trades=0,
            delta_percent=0.0,
            survived=False,
        )

    kept = sorted(result.trades, key=lambda t: t.net_pnl)[: max(0, len(result.trades) - count)]
    net = sum(t.net_pnl for t in kept) / config.initial_capital * 100.0
    # Both sides measured the same way. The run's own net_profit_percent
    # compounds position sizing on changing equity, so comparing this
    # simple sum against it would report a difference that came from the
    # two measures rather than from the trades removed.
    comparable_base = sum(t.net_pnl for t in result.trades) / config.initial_capital * 100.0
    return StressCase(
        name=f"Best {count} trades removed",
        description=(
            "How much of the return came from a handful of trades. A "
            "strategy that needs its top five is a bet on those five. "
            "Both figures are the trades added up against starting capital, "
            "not a compounded curve, so a number past -100% is the sum "
            "saying so rather than an account losing more than it held."
        ),
        net_percent=net,
        max_drawdown_percent=float(result.stats["max_drawdown_percent"]),
        trades=len(kept),
        delta_percent=net - comparable_base,
        survived=net > 0,
    )


def parameter_surface(
    strategy: Strategy,
    bars: Bars,
    *,
    grid: dict[str, list[float]],
    config: BacktestConfig | None = None,
    funding: list[FundingEvent] | None = None,
) -> ParameterSurface:
    """Run a parameter grid and judge whether the best point is a plateau.

    A setting that works only at one value, with worse results either
    side, is almost always an artefact of this particular history. A
    plateau — neighbours that do nearly as well — is what a real effect
    looks like.
    """
    import itertools

    config = config or BacktestConfig()
    names = sorted(grid)
    if not names:
        return ParameterSurface([], None, 0.0, False)

    points: list[ParameterPoint] = []
    for values in itertools.product(*(grid[name] for name in names)):
        params = dict(zip(names, values, strict=True))
        trial = Strategy(
            name=strategy.name,
            long_entry=strategy.long_entry,
            short_entry=strategy.short_entry,
            exits=strategy.exits,
            params={**strategy.params, **params},
        )
        net, drawdown, trades = _run(trial, bars, config, funding)
        points.append(
            ParameterPoint(
                params=params, net_percent=net, max_drawdown_percent=drawdown, trades=trades
            )
        )

    best = max(points, key=lambda p: p.net_percent)
    neighbours = [p for p in points if p is not best and _adjacent(p.params, best.params, grid)]
    mean = float(np.mean([p.net_percent for p in neighbours])) if neighbours else best.net_percent
    # Neighbours holding most of the peak is a plateau; a peak standing
    # alone is a fit to this history.
    plateau = bool(neighbours) and mean >= best.net_percent * 0.6 if best.net_percent > 0 else False

    return ParameterSurface(
        points=points, best=best, neighbourhood_mean_percent=mean, plateau=plateau
    )


def _adjacent(a: dict[str, float], b: dict[str, float], grid: dict[str, list[float]]) -> bool:
    """One step away on the grid in exactly one parameter."""
    steps = 0
    for name, values in grid.items():
        if a[name] == b[name]:
            continue
        order = sorted(values)
        if abs(order.index(a[name]) - order.index(b[name])) != 1:
            return False
        steps += 1
    return steps == 1
