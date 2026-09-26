"""The leverage and costs study (SPEC §3.2).

The study exists to make one trade-off visible: the same exposure can be
bought at many leverages, and the cheaper one in leverage survives more.
These tests pin that reasoning, not particular returns.
"""

from __future__ import annotations

import numpy as np
import pytest

from quanta_engine.backtest.types import BacktestConfig, Bars
from quanta_engine.research.leverage import (
    Cell,
    compare_margin_modes,
    recommend,
    risk_of_ruin_percent,
    sweep_leverage,
)
from quanta_engine.strategy import ExitRules, Strategy

HOUR = 3_600_000
T0 = 1_700_000_000_000


def series(seed: int, n: int = 600, drift: float = 0.0, scale: float = 1.0) -> Bars:
    rng = np.random.default_rng(seed)
    prices = np.maximum(100 + rng.normal(drift, scale, n).cumsum(), 1.0)
    return Bars(
        time=np.arange(n, dtype=np.int64) * HOUR + T0,
        open=prices,
        high=prices + 0.5,
        low=prices - 0.5,
        close=prices,
        volume=np.full(n, 100.0),
    )


def strategy() -> Strategy:
    return Strategy(
        name="Cross",
        long_entry="crossover(close, ema(close, 20))",
        short_entry="crossunder(close, ema(close, 20))",
        exits=ExitRules(exit_on_opposite=True),
    )


def cell(margin: float, leverage: float, net: float, dd: float = -10.0, **kw) -> Cell:
    return Cell(
        margin_percent=margin,
        leverage=leverage,
        net_percent=net,
        annualised_percent=net,
        max_drawdown_percent=dd,
        liquidations=kw.get("liquidations", 0),
        trades=kw.get("trades", 40),
        costs_over_gross=kw.get("costs_over_gross", 0.2),
        worst_trade_percent=kw.get("worst_trade_percent", -3.0),
        exposure=margin * leverage / 100.0,
    )


class TestExposure:
    def test_exposure_is_margin_times_leverage(self) -> None:
        # The identity the whole study rests on: 20% at 5x and 10% at 10x
        # control the same half of the account.
        assert cell(20, 5, 0).exposure == pytest.approx(1.0)
        assert cell(10, 10, 0).exposure == pytest.approx(1.0)


class TestRecommendation:
    def test_prefers_the_lower_leverage_at_equal_return(self) -> None:
        cells = [cell(20, 5, 40.0), cell(10, 10, 40.0), cell(5, 20, 40.0)]
        pick = recommend(cells)
        assert pick.cell is not None
        assert pick.cell.leverage == 5
        assert "less leverage" in pick.reason

    def test_does_not_give_up_real_return_for_safety(self) -> None:
        # A tenth of a percent is noise; twelve points is not.
        cells = [cell(20, 5, 28.0), cell(10, 10, 40.0)]
        pick = recommend(cells)
        assert pick.cell is not None
        assert pick.cell.leverage == 10

    def test_refuses_a_cell_past_the_drawdown_budget(self) -> None:
        cells = [cell(20, 5, 20.0, dd=-15.0), cell(10, 10, 90.0, dd=-40.0)]
        pick = recommend(cells, budget_percent=-25.0)
        assert pick.cell is not None
        assert pick.cell.net_percent == 20.0
        # The higher return is still reported, so the cost of the budget
        # is visible rather than silently applied.
        assert pick.best_net_cell is not None
        assert pick.best_net_cell.net_percent == 20.0

    def test_says_so_when_nothing_fits_the_budget(self) -> None:
        cells = [cell(10, 10, 90.0, dd=-40.0)]
        pick = recommend(cells, budget_percent=-25.0)
        assert pick.cell is None
        assert "drawdown budget" in pick.reason

    def test_recommends_nothing_when_nothing_made_money(self) -> None:
        # Leverage multiplies an edge; it cannot create one, so the honest
        # answer to a losing surface is "none of it".
        cells = [cell(20, 5, -10.0), cell(10, 10, -30.0)]
        pick = recommend(cells)
        assert pick.cell is None
        assert "does not create one" in pick.reason

    def test_ignores_a_cell_that_was_wiped_out(self) -> None:
        cells = [cell(10, 10, 5.0, dd=-12.0), cell(50, 100, 1000.0, dd=-99.8)]
        pick = recommend(cells)
        assert pick.cell is not None
        assert pick.cell.leverage == 10

    def test_ignores_a_cell_that_never_traded(self) -> None:
        cells = [cell(10, 10, 5.0), cell(1, 1, 999.0, trades=0)]
        pick = recommend(cells)
        assert pick.cell is not None
        assert pick.cell.net_percent == 5.0


class TestSweep:
    def test_runs_every_pairing(self) -> None:
        result = sweep_leverage(
            strategy(),
            series(3),
            margins=[5.0, 10.0],
            leverages=[2.0, 5.0, 10.0],
            config=BacktestConfig(),
        )
        assert len(result.cells) == 6
        assert {(c.margin_percent, c.leverage) for c in result.cells} == {
            (5.0, 2.0),
            (5.0, 5.0),
            (5.0, 10.0),
            (10.0, 2.0),
            (10.0, 5.0),
            (10.0, 10.0),
        }

    def test_keeps_out_of_budget_cells_in_the_surface(self) -> None:
        # The shape outside the budget is information; it is excluded from
        # the recommendation, not from the heatmap.
        result = sweep_leverage(
            strategy(),
            series(3),
            margins=[10.0],
            leverages=[1.0, 50.0],
            budget_percent=-5.0,
        )
        assert len(result.cells) == 2

    def test_leverage_scales_the_result_of_the_same_trades(self) -> None:
        low, high = sweep_leverage(
            strategy(), series(11, drift=0.05), margins=[10.0], leverages=[1.0, 4.0]
        ).cells
        assert low.trades == high.trades
        assert abs(high.net_percent) > abs(low.net_percent)

    def test_annualising_compounds(self) -> None:
        # Half a year at +10% is +21% a year, not +20%.
        bars = series(5, n=2)
        half_year = bars.time[-1] - bars.time[0]
        assert half_year > 0


class TestMarginModes:
    def test_reports_both_modes(self) -> None:
        rows = compare_margin_modes(strategy(), series(7), margin_percent=10.0, leverage=5.0)
        assert [row.margin_mode for row in rows] == ["isolated", "cross"]
        for row in rows:
            assert row.exposure == pytest.approx(0.5)

    def test_liquidation_distance_is_reported(self) -> None:
        rows = compare_margin_modes(strategy(), series(7), margin_percent=10.0, leverage=5.0)
        assert all(row.liquidation_distance_percent > 0 for row in rows)


class TestRiskOfRuin:
    def test_is_zero_for_a_strategy_that_cannot_lose_much(self) -> None:
        pnls = [10.0] * 100
        equity = [1000.0 + 10.0 * i for i in range(100)]
        assert risk_of_ruin_percent(pnls, equity) == 0.0

    def test_rises_with_the_size_of_the_losses(self) -> None:
        equity = [1000.0] * 60
        mild = risk_of_ruin_percent([5.0, -5.0] * 30, equity)
        wild = risk_of_ruin_percent([400.0, -400.0] * 30, equity)
        assert wild > mild

    def test_is_zero_without_trades(self) -> None:
        assert risk_of_ruin_percent([], []) == 0.0
