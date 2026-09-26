"""Paper trading and the gate it puts in front of real money."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.models.paper import PaperFill, PaperSession
from quanta.services.paper_service import (
    MAX_DRIFT_PERCENT,
    evaluate_promotion,
    execution_quality,
)
from tests.test_forward_routes import auth, make_strategy, seed


def session(**overrides) -> PaperSession:
    defaults: dict[str, object] = {
        "started_at": datetime.now(UTC) - timedelta(days=20),
        "initial_capital": 10_000.0,
        "equity": 10_500.0,
        "expected_low_percent": -10.0,
        "expected_high_percent": 20.0,
        "drawdown_limit_percent": -25.0,
        "missed_signals": 0,
    }
    defaults.update(overrides)
    return PaperSession(**defaults)


def fill(slippage_bps: float = 1.0, equity: float = 10_100.0, **overrides) -> PaperFill:
    defaults: dict[str, object] = {
        "side": "long",
        "action": "entry",
        "bar_time": 0,
        "signal_price": 100.0,
        "fill_price": 100.0,
        "slippage_bps": slippage_bps,
        "latency_ms": 120,
        "fee": 0.6,
        "funding": 0.0,
        "net_pnl": 10.0,
        "equity_after": equity,
        "filled_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return PaperFill(**defaults)


class TestExecutionQuality:
    def test_an_empty_session_reports_zeros_not_nothing(self) -> None:
        quality = execution_quality([])
        assert quality["fills"] == 0
        assert quality["drift_percent"] == 0.0

    def test_drift_is_the_mean_slippage_in_percent(self) -> None:
        # The number the checklist gates on: a strategy whose edge is
        # smaller than its drift has no edge.
        quality = execution_quality([fill(slippage_bps=2.0), fill(slippage_bps=4.0)])
        assert quality["mean_slippage_bps"] == pytest.approx(3.0)
        assert quality["drift_percent"] == pytest.approx(0.03)

    def test_costs_are_summed_not_averaged(self) -> None:
        quality = execution_quality([fill(fee=1.0), fill(fee=2.0, funding=0.5)])
        assert quality["total_fees"] == pytest.approx(3.0)
        assert quality["total_funding"] == pytest.approx(0.5)


class TestPromotionChecklist:
    def test_a_healthy_session_passes_every_check(self) -> None:
        fills = [fill(slippage_bps=1.0, equity=10_000 + i * 10) for i in range(40)]
        promotion = evaluate_promotion(session(equity=10_400.0), fills)
        assert promotion.ready is True
        assert promotion.blocking == []

    def test_too_few_days_blocks_it(self) -> None:
        fresh = session(started_at=datetime.now(UTC) - timedelta(days=3))
        promotion = evaluate_promotion(fresh, [fill() for _ in range(40)])
        assert promotion.ready is False
        assert any("days" in reason for reason in promotion.blocking)

    def test_too_few_trades_blocks_it(self) -> None:
        promotion = evaluate_promotion(session(), [fill() for _ in range(5)])
        assert promotion.ready is False
        assert any("trades" in reason for reason in promotion.blocking)

    def test_a_result_outside_the_expected_range_blocks_it(self) -> None:
        # Doing far better than the backtest said is as much a reason to
        # look again as doing worse: something is different.
        wild = session(equity=90_000.0)
        promotion = evaluate_promotion(wild, [fill() for _ in range(40)])
        assert promotion.ready is False
        assert any("expected range" in reason for reason in promotion.blocking)

    def test_drift_past_the_limit_blocks_it(self) -> None:
        heavy = [fill(slippage_bps=50.0) for _ in range(40)]
        promotion = evaluate_promotion(session(), heavy)
        assert promotion.ready is False
        assert any("drift" in reason.lower() for reason in promotion.blocking)
        drift = execution_quality(heavy)["drift_percent"]
        assert drift > MAX_DRIFT_PERCENT

    def test_a_drawdown_past_the_limit_blocks_it(self) -> None:
        crash = [fill(equity=10_000.0), fill(equity=6_000.0), *[fill() for _ in range(40)]]
        promotion = evaluate_promotion(session(drawdown_limit_percent=-25.0), crash)
        assert any("Drawdown" in reason for reason in promotion.blocking)

    def test_every_check_carries_its_evidence(self) -> None:
        # A checklist that says "failed" without saying what the number
        # was cannot be acted on.
        promotion = evaluate_promotion(session(), [fill()])
        assert all(check.detail for check in promotion.checks)


class TestRoutes:
    async def test_a_session_runs_takes_fills_and_reports(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=60)
        strategy_id = await make_strategy(client, api_prefix, headers)
        setup = await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json={
                "name": "BTC 1h",
                "strategy_id": strategy_id,
                "symbol": "BTCUSDT",
                "interval": "1h",
                "margin_percent": 10,
                "leverage": 5,
            },
        )
        assert setup.status_code == 201, setup.text

        started = await client.post(
            f"{api_prefix}/paper",
            headers=headers,
            json={
                "setup_id": setup.json()["id"],
                "initial_capital": 10_000,
                "expected_low_percent": -10,
                "expected_high_percent": 20,
            },
        )
        assert started.status_code == 201, started.text
        session_id = started.json()["id"]
        assert started.json()["promotion"]["ready"] is False

        filled = await client.post(
            f"{api_prefix}/paper/{session_id}/fills",
            headers=headers,
            json={
                "side": "long",
                "bar_time": 1,
                "signal_price": 100.0,
                "fill_price": 100.05,
                "latency_ms": 90,
                "net_pnl": 12.0,
            },
        )
        assert filled.status_code == 201, filled.text
        body = filled.json()
        assert body["equity"] == pytest.approx(10_012.0)
        # A long filled above its signal is adverse.
        assert body["execution"]["mean_slippage_bps"] > 0

    async def test_a_missed_signal_is_counted(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        # A strategy whose signals routinely find nobody to trade against
        # is not tradeable, and a backtest cannot see that at all.
        headers = await auth(client, api_prefix)
        await seed(db, days=60)
        strategy_id = await make_strategy(client, api_prefix, headers)
        setup = await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json={
                "name": "BTC missed",
                "strategy_id": strategy_id,
                "symbol": "BTCUSDT",
                "margin_percent": 10,
                "leverage": 5,
            },
        )
        started = await client.post(
            f"{api_prefix}/paper", headers=headers, json={"setup_id": setup.json()["id"]}
        )
        session_id = started.json()["id"]

        missed = await client.post(f"{api_prefix}/paper/{session_id}/missed", headers=headers)
        assert missed.status_code == 202
        assert missed.json()["missed_signals"] == 1

    async def test_promotion_is_refused_with_the_reason(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=60)
        strategy_id = await make_strategy(client, api_prefix, headers)
        setup = await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json={
                "name": "BTC promote",
                "strategy_id": strategy_id,
                "symbol": "BTCUSDT",
                "margin_percent": 10,
                "leverage": 5,
            },
        )
        setup_id = setup.json()["id"]
        # The gate SPEC §3.3 puts in the data: the bot flag starts false.
        assert setup.json()["use_in_bot"] is False

        started = await client.post(
            f"{api_prefix}/paper", headers=headers, json={"setup_id": setup_id}
        )
        session_id = started.json()["id"]

        refused = await client.post(
            f"{api_prefix}/paper/{session_id}/promote", headers=headers, json={}
        )
        assert refused.status_code == 422
        assert "not ready" in refused.json()["detail"].lower()

        # And the setup is still locked out of the bot.
        current = await client.get(f"{api_prefix}/setups/{setup_id}", headers=headers)
        assert current.json()["use_in_bot"] is False

    async def test_an_override_needs_two_factor_enabled(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        # Without 2FA there is no second factor to check, so the override
        # SPEC §3.3 allows is not available.
        headers = await auth(client, api_prefix)
        await seed(db, days=60)
        strategy_id = await make_strategy(client, api_prefix, headers)
        setup = await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json={
                "name": "BTC override",
                "strategy_id": strategy_id,
                "symbol": "BTCUSDT",
                "margin_percent": 10,
                "leverage": 5,
            },
        )
        started = await client.post(
            f"{api_prefix}/paper", headers=headers, json={"setup_id": setup.json()["id"]}
        )
        response = await client.post(
            f"{api_prefix}/paper/{started.json()['id']}/promote",
            headers=headers,
            json={"override": True},
        )
        assert response.status_code == 403
        assert "two-factor" in response.json()["detail"]

    async def test_a_stopped_session_takes_no_more_fills(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=60)
        strategy_id = await make_strategy(client, api_prefix, headers)
        setup = await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json={
                "name": "BTC stop",
                "strategy_id": strategy_id,
                "symbol": "BTCUSDT",
                "margin_percent": 10,
                "leverage": 5,
            },
        )
        started = await client.post(
            f"{api_prefix}/paper", headers=headers, json={"setup_id": setup.json()["id"]}
        )
        session_id = started.json()["id"]
        await client.post(f"{api_prefix}/paper/{session_id}/stop", headers=headers)

        response = await client.post(
            f"{api_prefix}/paper/{session_id}/fills",
            headers=headers,
            json={"side": "long", "bar_time": 1, "signal_price": 100, "fill_price": 100},
        )
        assert response.status_code == 409

    async def test_a_session_is_private_to_its_owner(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        from tests.test_research_routes import other_user

        headers = await auth(client, api_prefix)
        await seed(db, days=60)
        strategy_id = await make_strategy(client, api_prefix, headers)
        setup = await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json={
                "name": "BTC private",
                "strategy_id": strategy_id,
                "symbol": "BTCUSDT",
                "margin_percent": 10,
                "leverage": 5,
            },
        )
        started = await client.post(
            f"{api_prefix}/paper", headers=headers, json={"setup_id": setup.json()["id"]}
        )
        theirs = await other_user(client, api_prefix)
        assert (
            await client.get(f"{api_prefix}/paper/{started.json()['id']}", headers=theirs)
        ).status_code == 404
