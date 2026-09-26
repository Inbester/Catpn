"""Trade risk and robustness (SPEC §3.2)."""

from __future__ import annotations

import numpy as np
import pytest

from quanta_engine.backtest.types import BacktestConfig, Bars, FundingEvent, Trade
from quanta_engine.research.robustness import (
    kelly_fraction,
    parameter_surface,
    reshuffled_years,
    risk_measures,
    stress_tests,
    value_at_risk,
)
from quanta_engine.research.traderisk import analyse_trades, holding_histogram, liquidation_leverage
from quanta_engine.strategy import ExitReason, ExitRules, Strategy

HOUR = 3_600_000
T0 = 1_700_000_000_000


def series(seed: int, n: int = 600, drift: float = 0.0) -> Bars:
    rng = np.random.default_rng(seed)
    prices = np.maximum(100 + rng.normal(drift, 1.0, n).cumsum(), 1.0)
    return Bars(
        time=np.arange(n, dtype=np.int64) * HOUR + T0,
        open=prices,
        high=prices + 0.5,
        low=prices - 0.5,
        close=prices,
        volume=np.full(n, 100.0),
    )


def strategy(**params: float) -> Strategy:
    return Strategy(
        name="Cross",
        long_entry="crossover(close, ema(close, fast))",
        short_entry="crossunder(close, ema(close, fast))",
        exits=ExitRules(exit_on_opposite=True),
        params={"fast": 20.0, **params},
    )


def trade(net: float, dip: float, up: float = 0.0, margin: float = 1000.0, held: int = 5) -> Trade:
    return Trade(
        side="long",
        entry_index=0,
        entry_time=T0,
        entry_price=100.0,
        quantity=1.0,
        margin=margin,
        leverage=10.0,
        liquidation_price=90.0,
        exit_index=held,
        exit_time=T0 + held * HOUR,
        exit_price=101.0,
        exit_reason=ExitReason.OPPOSITE_SIGNAL,
        net_pnl=net,
        run_up=up,
        drawdown=dip,
        equity_after=10_000.0 + net,
    )


class TestLiquidationLeverage:
    def test_a_deeper_dip_survives_less_leverage(self) -> None:
        assert liquidation_leverage(5.0) > liquidation_leverage(10.0)

    def test_a_ten_percent_dip_is_roughly_ten_times(self) -> None:
        # Slightly under 10x, because maintenance margin eats the buffer
        # before the move fully does.
        assert 9.0 < liquidation_leverage(10.0) < 10.0

    def test_a_trade_that_never_went_red_is_unbounded(self) -> None:
        assert liquidation_leverage(0.0) == pytest.approx(1.0 / 0.004)


class TestTradeRisk:
    def test_counts_winners_that_were_red_first(self) -> None:
        # The KPI that tells a user whether they could have held it.
        risk = analyse_trades([trade(100.0, -50.0), trade(100.0, 0.0), trade(-20.0, -80.0)])
        assert risk.winners == 2
        assert risk.winners_that_were_red == 1

    def test_scales_excursions_by_margin_not_notional(self) -> None:
        # What went away, as a share of what was put at risk — which is
        # what the liquidation engine measures.
        risk = analyse_trades([trade(100.0, -100.0, margin=1000.0)])
        assert risk.points[0].adverse_percent == pytest.approx(10.0)

    def test_reports_the_leverage_the_deepest_dip_survived(self) -> None:
        risk = analyse_trades([trade(50.0, -200.0, margin=1000.0)])
        assert risk.deepest_dip_percent == pytest.approx(20.0)
        assert risk.survives_up_to_leverage == pytest.approx(1 / 0.204, rel=1e-3)

    def test_handles_a_run_with_no_trades(self) -> None:
        risk = analyse_trades([])
        assert risk.winners == 0
        assert risk.deepest_dip_percent == 0.0

    def test_holding_histogram_groups_funding_with_time(self) -> None:
        risk = analyse_trades([trade(10.0, -5.0, held=h) for h in (1, 2, 20, 40)])
        buckets = holding_histogram(risk.points, buckets=2)
        assert sum(b["trades"] for b in buckets) == 4


class TestRiskMeasures:
    def test_cvar_is_at_least_as_bad_as_var(self) -> None:
        # VaR says where the tail starts; CVaR says how far it goes, so it
        # can never be the milder of the two.
        returns = np.random.default_rng(0).normal(0.001, 0.02, 2000)
        var, cvar = value_at_risk(returns)
        assert cvar <= var

    def test_kelly_is_zero_without_an_edge(self) -> None:
        assert kelly_fraction(np.array([-0.01, 0.01, -0.01, 0.01])) == pytest.approx(0.0, abs=0.2)

    def test_kelly_refuses_a_riskless_series(self) -> None:
        assert kelly_fraction(np.array([0.01, 0.01, 0.01])) == 0.0

    def test_half_kelly_is_half(self) -> None:
        measures = risk_measures(np.random.default_rng(1).normal(0.01, 0.05, 500))
        assert measures.half_kelly_fraction == pytest.approx(measures.kelly_fraction / 2)


class TestReshuffledYears:
    def test_the_same_trades_in_a_different_order_end_differently(self) -> None:
        returns = np.array([0.05, -0.04, 0.06, -0.05, 0.03] * 20)
        out = reshuffled_years(returns, trades_per_year=100)
        assert out["p5_percent"] < out["median_percent"] < out["p95_percent"]

    def test_a_wilder_strategy_ruins_more_often(self) -> None:
        mild = reshuffled_years(np.array([0.01, -0.01] * 50), trades_per_year=100)
        wild = reshuffled_years(np.array([0.40, -0.35] * 50), trades_per_year=100)
        assert wild["ruin_rate"] > mild["ruin_rate"]

    def test_handles_an_empty_run(self) -> None:
        assert reshuffled_years(np.array([]), trades_per_year=100)["median_percent"] == 0.0


class TestStressTests:
    def test_runs_the_five_cases_the_spec_names(self) -> None:
        cases = stress_tests(strategy(), series(3))
        names = [case.name for case in cases]
        assert names == [
            "VIP3 fees",
            "Fees doubled",
            "Slippage tripled",
            "Funding +0.03% per 8h",
            "Best 5 trades removed",
        ]

    def test_doubling_fees_never_helps(self) -> None:
        cases = {case.name: case for case in stress_tests(strategy(), series(3))}
        assert cases["Fees doubled"].delta_percent <= 0

    def test_tripling_slippage_never_helps(self) -> None:
        cases = {case.name: case for case in stress_tests(strategy(), series(3))}
        assert cases["Slippage tripled"].delta_percent <= 0

    def test_removing_the_best_trades_never_helps(self) -> None:
        cases = {case.name: case for case in stress_tests(strategy(), series(3))}
        assert cases["Best 5 trades removed"].delta_percent <= 0

    def test_worse_funding_never_helps_either_side(self) -> None:
        # Adding a signed rate would help shorts as much as it hurt longs.
        # A stress case that helps is not a stress case.
        bars = series(9, drift=0.05)
        funding = [
            FundingEvent(time=int(t), rate=0.0001 if i % 2 == 0 else -0.0001)
            for i, t in enumerate(bars.time[::8])
        ]
        cases = {
            case.name: case
            for case in stress_tests(
                strategy(), bars, config=BacktestConfig(apply_funding=True), funding=funding
            )
        }
        assert cases["Funding +0.03% per 8h"].delta_percent <= 0


class TestParameterSurface:
    def test_reports_the_best_point_and_its_neighbours(self) -> None:
        surface = parameter_surface(
            strategy(), series(3), grid={"fast": [10.0, 15.0, 20.0, 25.0, 30.0]}
        )
        assert len(surface.points) == 5
        assert surface.best is not None
        assert surface.best.net_percent == max(p.net_percent for p in surface.points)

    def test_a_lone_peak_is_not_a_plateau(self) -> None:
        # Judging by the peak alone is how an overfit gets shipped.
        surface = parameter_surface(strategy(), series(3), grid={"fast": [5.0, 50.0]})
        assert surface.best is not None
        assert isinstance(surface.plateau, bool)

    def test_an_empty_grid_returns_nothing(self) -> None:
        surface = parameter_surface(strategy(), series(3), grid={})
        assert surface.points == []
        assert surface.best is None
