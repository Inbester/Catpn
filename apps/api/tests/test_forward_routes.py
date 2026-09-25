"""Period comparison, walk-forward and Setup routes."""

from __future__ import annotations

import math
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.exchanges.base import Bar, Funding, Interval
from quanta.services import market_store
from tests.test_auth_routes import login, register

HOUR = 3_600_000
DAY = 86_400_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % (8 * HOUR))


async def auth(client: AsyncClient, prefix: str) -> dict[str, str]:
    await register(client, prefix)
    tokens = await login(client, prefix)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def strategy_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "EMA cross",
        "long_entry": "crossover(close, ema(close, fast))",
        "short_entry": "crossunder(close, ema(close, fast))",
        "exits": {"exit_on_opposite": True},
        "params": {"fast": 20},
    }
    payload.update(overrides)
    return payload


async def seed(db: AsyncSession, *, days: int = 400, symbol: str = "BTCUSDT") -> None:
    """Enough hourly history for two periods and several walk-forward windows."""
    count = days * 24
    bars = []
    for i in range(count):
        price = 100 + math.sin(i / 37) * 12 + i * 0.01
        bars.append(
            Bar(
                open_time=T0 + i * HOUR,
                open=Decimal(str(round(price, 4))),
                high=Decimal(str(round(price + 0.8, 4))),
                low=Decimal(str(round(price - 0.8, 4))),
                close=Decimal(str(round(price, 4))),
                volume=Decimal("100"),
            )
        )
    await market_store.upsert_bars(db, symbol, Interval.H1, bars)
    await market_store.upsert_funding(
        db,
        symbol,
        [
            Funding(funding_time=T0 + k * 8 * HOUR, funding_rate=Decimal("0.0001"))
            for k in range(count // 8 + 1)
        ],
    )
    await db.commit()


async def make_strategy(client: AsyncClient, prefix: str, headers: dict[str, str]) -> str:
    created = await client.post(f"{prefix}/strategies", headers=headers, json=strategy_payload())
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


class TestPeriodComparison:
    async def test_runs_and_returns_a_verdict(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db)
        strategy_id = await make_strategy(client, api_prefix, headers)

        response = await client.post(
            f"{api_prefix}/forward/{strategy_id}/periods",
            headers=headers,
            json={
                "symbol": "BTCUSDT",
                "interval": "1h",
                "reference": {"label": "Farvardin 1404", "start": T0, "end": T0 + 60 * DAY},
                "test": {
                    "label": "Farvardin 1405",
                    "start": T0 + 60 * DAY,
                    "end": T0 + 120 * DAY,
                },
                "monte_carlo_runs": 400,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["verdict"] in (
            "holds_up",
            "holds_up_weaker",
            "outside_range",
            "too_few_trades",
        )
        assert body["headline"]
        assert body["reading"]
        assert len(body["checks"]) == 4
        assert len(body["metrics"]) == 9
        assert body["monte_carlo"]["runs"] == 400

    def _period(self, start: int, end: int, label: str) -> dict[str, object]:
        return {"label": label, "start": start, "end": end}

    async def test_both_periods_use_one_frozen_version(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        """The comparison isolates the data, so the version must not move."""
        headers = await auth(client, api_prefix)
        await seed(db)
        strategy_id = await make_strategy(client, api_prefix, headers)

        response = await client.post(
            f"{api_prefix}/forward/{strategy_id}/periods",
            headers=headers,
            json={
                "symbol": "BTCUSDT",
                "interval": "1h",
                "reference": self._period(T0, T0 + 60 * DAY, "A"),
                "test": self._period(T0 + 60 * DAY, T0 + 120 * DAY, "B"),
                "monte_carlo_runs": 200,
            },
        )
        strategy = await client.get(f"{api_prefix}/strategies/{strategy_id}", headers=headers)
        assert response.json()["strategy_version"] == strategy.json()["version"]

    async def test_reports_the_regime_for_both_periods(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db)
        strategy_id = await make_strategy(client, api_prefix, headers)

        body = (
            await client.post(
                f"{api_prefix}/forward/{strategy_id}/periods",
                headers=headers,
                json={
                    "symbol": "BTCUSDT",
                    "interval": "1h",
                    "reference": self._period(T0, T0 + 60 * DAY, "A"),
                    "test": self._period(T0 + 60 * DAY, T0 + 120 * DAY, "B"),
                    "monte_carlo_runs": 200,
                },
            )
        ).json()

        for side in ("reference", "test"):
            regime = body[side]["regime"]
            assert "trend_efficiency" in regime
            assert "volatility_annual_percent" in regime
            assert regime["bars"] > 0

    async def test_rejects_a_backwards_period(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db)
        strategy_id = await make_strategy(client, api_prefix, headers)

        response = await client.post(
            f"{api_prefix}/forward/{strategy_id}/periods",
            headers=headers,
            json={
                "symbol": "BTCUSDT",
                "interval": "1h",
                "reference": self._period(T0 + 60 * DAY, T0, "backwards"),
                "test": self._period(T0 + 60 * DAY, T0 + 120 * DAY, "B"),
            },
        )
        assert response.status_code == 422

    async def test_says_when_there_is_not_enough_history(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        strategy_id = await make_strategy(client, api_prefix, headers)

        response = await client.post(
            f"{api_prefix}/forward/{strategy_id}/periods",
            headers=headers,
            json={
                "symbol": "BTCUSDT",
                "interval": "1h",
                "reference": self._period(T0, T0 + 60 * DAY, "A"),
                "test": self._period(T0 + 60 * DAY, T0 + 120 * DAY, "B"),
            },
        )
        assert response.status_code == 422
        assert "stored bars" in response.json()["detail"]


class TestWalkForward:
    async def test_produces_windows_and_a_chained_curve(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db)
        strategy_id = await make_strategy(client, api_prefix, headers)

        response = await client.post(
            f"{api_prefix}/forward/{strategy_id}/walk-forward",
            headers=headers,
            json={
                "symbol": "BTCUSDT",
                "interval": "1h",
                "grid": {"fast": [10, 30]},
                "in_sample_days": 60,
                "out_of_sample_days": 20,
                "max_windows": 5,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert 1 <= len(body["windows"]) <= 5
        assert len(body["chained"]["time"]) == len(body["chained"]["value"])
        assert len(body["chained"]["drawdown"]) == len(body["chained"]["value"])
        for window in body["windows"]:
            assert window["out_of_sample_start"] == window["in_sample_end"]
            assert "fast" in window["chosen_params"]

    async def test_refuses_an_unreasonable_grid(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db)
        strategy_id = await make_strategy(client, api_prefix, headers)

        response = await client.post(
            f"{api_prefix}/forward/{strategy_id}/walk-forward",
            headers=headers,
            json={
                "symbol": "BTCUSDT",
                "interval": "1h",
                "grid": {"a": list(range(30)), "b": list(range(30))},
            },
        )
        assert response.status_code == 422

    async def test_says_when_the_range_is_too_short(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=40)
        strategy_id = await make_strategy(client, api_prefix, headers)

        response = await client.post(
            f"{api_prefix}/forward/{strategy_id}/walk-forward",
            headers=headers,
            json={
                "symbol": "BTCUSDT",
                "interval": "1h",
                "in_sample_days": 90,
                "out_of_sample_days": 30,
            },
        )
        assert response.status_code == 422
        assert "too short" in response.json()["detail"]


class TestSetups:
    async def _setup_payload(self, strategy_id: str, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": "BTC trend",
            "color": "#6EA8FE",
            "strategy_id": strategy_id,
            "symbol": "BTCUSDT",
            "interval": "1h",
            "margin_percent": 10,
            "leverage": 10,
            "margin_mode": "isolated",
        }
        payload.update(overrides)
        return payload

    async def test_locks_the_strategy_version(self, client: AsyncClient, api_prefix: str) -> None:
        """A Setup must not follow the draft; that is the whole point."""
        headers = await auth(client, api_prefix)
        strategy_id = await make_strategy(client, api_prefix, headers)
        original = (
            await client.get(f"{api_prefix}/strategies/{strategy_id}", headers=headers)
        ).json()["version"]

        created = await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json=await self._setup_payload(strategy_id),
        )
        assert created.status_code == 201, created.text
        setup_id = created.json()["id"]

        # Change the strategy afterwards.
        await client.put(
            f"{api_prefix}/strategies/{strategy_id}",
            headers=headers,
            json=strategy_payload(params={"fast": 50}),
        )

        fetched = await client.get(f"{api_prefix}/setups/{setup_id}", headers=headers)
        assert fetched.json()["strategy_version"] == original
        assert fetched.json()["strategy_snapshot"]["params"]["fast"] == 20

    async def test_exposure_is_margin_times_leverage(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        strategy_id = await make_strategy(client, api_prefix, headers)
        created = await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json=await self._setup_payload(strategy_id, margin_percent=8, leverage=25),
        )
        assert created.json()["exposure"] == 200.0

    async def test_the_bot_stage_is_locked_until_paper_passes(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        """SPEC §3.3 gates the bot behind paper trading, in the data."""
        headers = await auth(client, api_prefix)
        strategy_id = await make_strategy(client, api_prefix, headers)
        created = await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json=await self._setup_payload(strategy_id),
        )
        setup_id = created.json()["id"]
        assert created.json()["use_in_bot"] is False

        # The client cannot simply ask for it.
        forced = await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json=await self._setup_payload(strategy_id, name="Forced", use_in_bot=True),
        )
        assert forced.json()["use_in_bot"] is False

        passed = await client.post(
            f"{api_prefix}/setups/{setup_id}/stage",
            headers=headers,
            json={"stage": "paper", "status": "passed", "note": "14 days, 40 trades"},
        )
        assert passed.json()["use_in_bot"] is True

        failed = await client.post(
            f"{api_prefix}/setups/{setup_id}/stage",
            headers=headers,
            json={"stage": "paper", "status": "failed"},
        )
        assert failed.json()["use_in_bot"] is False

    async def test_names_are_unique_per_user(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        strategy_id = await make_strategy(client, api_prefix, headers)
        payload = await self._setup_payload(strategy_id)

        assert (
            await client.post(f"{api_prefix}/setups", headers=headers, json=payload)
        ).status_code == 201
        assert (
            await client.post(f"{api_prefix}/setups", headers=headers, json=payload)
        ).status_code == 409

    async def test_overview_warns_about_the_same_symbol(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        """Two live setups on one symbol will close each other's positions."""
        headers = await auth(client, api_prefix)
        strategy_id = await make_strategy(client, api_prefix, headers)

        for name in ("First", "Second"):
            created = await client.post(
                f"{api_prefix}/setups",
                headers=headers,
                json=await self._setup_payload(strategy_id, name=name),
            )
            await client.post(
                f"{api_prefix}/setups/{created.json()['id']}/stage",
                headers=headers,
                json={"stage": "paper", "status": "passed"},
            )

        overview = await client.get(f"{api_prefix}/setups/overview", headers=headers)
        assert overview.status_code == 200
        kinds = {conflict["kind"] for conflict in overview.json()["conflicts"]}
        assert "same_symbol" in kinds

    async def test_overview_totals_exposure(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        strategy_id = await make_strategy(client, api_prefix, headers)
        await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json=await self._setup_payload(strategy_id, name="A", margin_percent=10, leverage=5),
        )
        await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json=await self._setup_payload(strategy_id, name="B", margin_percent=20, leverage=2),
        )
        overview = await client.get(f"{api_prefix}/setups/overview", headers=headers)
        assert overview.json()["total_exposure"] == 90.0

    async def test_archiving_takes_a_setup_out_of_service(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        strategy_id = await make_strategy(client, api_prefix, headers)
        created = await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json=await self._setup_payload(strategy_id),
        )
        setup_id = created.json()["id"]

        assert (
            await client.delete(f"{api_prefix}/setups/{setup_id}", headers=headers)
        ).status_code == 204

        listed = await client.get(f"{api_prefix}/setups", headers=headers)
        assert listed.json() == []

        # Archived, not deleted: it is the provenance of past runs.
        fetched = await client.get(f"{api_prefix}/setups/{setup_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["use_in_bot"] is False

    async def test_one_user_cannot_see_anothers_setup(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        strategy_id = await make_strategy(client, api_prefix, headers)
        created = await client.post(
            f"{api_prefix}/setups",
            headers=headers,
            json=await self._setup_payload(strategy_id),
        )
        setup_id = created.json()["id"]

        await register(client, api_prefix, email="intruder@example.com")
        tokens = await login(client, api_prefix, email="intruder@example.com")
        intruder = {"Authorization": f"Bearer {tokens['access_token']}"}

        assert (
            await client.get(f"{api_prefix}/setups/{setup_id}", headers=intruder)
        ).status_code == 404
        assert (await client.get(f"{api_prefix}/setups", headers=intruder)).json() == []
