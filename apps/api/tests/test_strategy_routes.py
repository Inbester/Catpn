"""Strategy CRUD, DSL validation and backtest routes."""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.exchanges.base import Bar, Funding, Interval
from quanta.services import market_store
from tests.test_auth_routes import login, register

MINUTE = 60_000
HOUR = 3_600_000
T0 = 1_700_000_000_000 - (1_700_000_000_000 % (8 * HOUR))


async def auth(client: AsyncClient, prefix: str) -> dict[str, str]:
    await register(client, prefix)
    tokens = await login(client, prefix)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def simple_strategy(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "EMA cross",
        "long_entry": "crossover(close, sma(close, 10))",
        "short_entry": "crossunder(close, sma(close, 10))",
        "exits": {"exit_on_opposite": True},
        "params": {},
    }
    payload.update(overrides)
    return payload


async def seed_bars(db: AsyncSession, count: int = 300, symbol: str = "BTCUSDT") -> None:
    """Store a wavy series so a crossover strategy actually trades."""
    import math

    bars = []
    for i in range(count):
        price = 100 + math.sin(i / 9) * 8 + i * 0.05
        bars.append(
            Bar(
                open_time=T0 + i * HOUR,
                open=Decimal(str(round(price, 4))),
                high=Decimal(str(round(price + 1, 4))),
                low=Decimal(str(round(price - 1, 4))),
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


class TestValidation:
    async def test_accepts_a_valid_strategy(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/strategies/validate", headers=headers, json=simple_strategy()
        )
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is True
        assert len(body["version"]) == 64
        assert body["normalized_long"] == "crossover(close, sma(close, 10.0))"

    async def test_reports_the_error_position_instead_of_a_4xx(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        """The editor underlines while typing, so this is a 200 with detail."""
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/strategies/validate",
            headers=headers,
            json=simple_strategy(long_entry="close > > 5"),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert body["position"] is not None
        assert "Unexpected" in body["error"]

    async def test_rejects_an_unknown_name(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/strategies/validate",
            headers=headers,
            json=simple_strategy(long_entry="close > mystery"),
        )
        assert response.json()["valid"] is False
        assert "mystery" in response.json()["error"]

    async def test_a_declared_parameter_is_known(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/strategies/validate",
            headers=headers,
            json=simple_strategy(long_entry="close > level", params={"level": 100}),
        )
        assert response.json()["valid"] is True

    async def test_sandbox_escapes_are_refused(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        for attempt in ("close.__class__", "__import__(os)", "eval(close)"):
            response = await client.post(
                f"{api_prefix}/strategies/validate",
                headers=headers,
                json=simple_strategy(long_entry=attempt),
            )
            assert response.json()["valid"] is False, attempt

    async def test_lists_the_available_functions(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        response = await client.get(f"{api_prefix}/strategies/functions", headers=headers)
        assert response.status_code == 200
        names = {entry["name"] for entry in response.json()}
        assert {"ema", "sma", "rsi", "crossover", "crossunder"} <= names


class TestStrategyCrud:
    async def test_creates_and_reads_back(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/strategies", headers=headers, json=simple_strategy()
        )
        assert created.status_code == 201
        body = created.json()
        assert body["name"] == "EMA cross"
        assert len(body["version"]) == 64

        fetched = await client.get(f"{api_prefix}/strategies/{body['id']}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["version"] == body["version"]

    async def test_rejects_an_invalid_strategy_on_save(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/strategies",
            headers=headers,
            json=simple_strategy(long_entry="close > "),
        )
        assert response.status_code == 422

    async def test_requires_at_least_one_entry(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/strategies",
            headers=headers,
            json=simple_strategy(long_entry=None, short_entry=None),
        )
        assert response.status_code == 422

    async def test_reformatting_does_not_change_the_version(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        """A Setup locks this hash, so whitespace must not move it."""
        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/strategies", headers=headers, json=simple_strategy()
        )
        original = created.json()

        updated = await client.put(
            f"{api_prefix}/strategies/{original['id']}",
            headers=headers,
            json=simple_strategy(long_entry="crossover( close , sma( close , 10 ) )   # tidy up"),
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == original["version"]

    async def test_changing_a_number_changes_the_version(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/strategies", headers=headers, json=simple_strategy()
        )
        original = created.json()

        updated = await client.put(
            f"{api_prefix}/strategies/{original['id']}",
            headers=headers,
            json=simple_strategy(long_entry="crossover(close, sma(close, 11))"),
        )
        assert updated.json()["version"] != original["version"]

    async def test_one_user_cannot_touch_anothers_strategy(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        owner = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/strategies", headers=owner, json=simple_strategy()
        )
        strategy_id = created.json()["id"]

        await register(client, api_prefix, email="intruder@example.com")
        tokens = await login(client, api_prefix, email="intruder@example.com")
        intruder = {"Authorization": f"Bearer {tokens['access_token']}"}

        assert (
            await client.get(f"{api_prefix}/strategies/{strategy_id}", headers=intruder)
        ).status_code == 404
        assert (
            await client.delete(f"{api_prefix}/strategies/{strategy_id}", headers=intruder)
        ).status_code == 404

    async def test_requires_authentication(self, client: AsyncClient, api_prefix: str) -> None:
        assert (await client.get(f"{api_prefix}/strategies")).status_code == 401


class TestBacktestRoute:
    async def test_runs_and_stores_a_result(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed_bars(db)

        created = await client.post(
            f"{api_prefix}/strategies", headers=headers, json=simple_strategy()
        )
        strategy_id = created.json()["id"]

        response = await client.post(
            f"{api_prefix}/strategies/{strategy_id}/backtest",
            headers=headers,
            json={"symbol": "BTCUSDT", "interval": "1h"},
        )
        assert response.status_code == 200, response.text

        body = response.json()
        assert body["strategy_version"] == created.json()["version"]
        assert body["stats"]["total_trades"] > 0
        assert len(body["equity"]["value"]) == len(body["equity"]["time"])
        assert len(body["trades"]) == body["stats"]["total_trades"]

    async def test_costs_are_applied(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        """A run with fees must report less profit than one without."""
        headers = await auth(client, api_prefix)
        await seed_bars(db)
        created = await client.post(
            f"{api_prefix}/strategies", headers=headers, json=simple_strategy()
        )
        strategy_id = created.json()["id"]

        async def net(**config: object) -> float:
            response = await client.post(
                f"{api_prefix}/strategies/{strategy_id}/backtest",
                headers=headers,
                json={"symbol": "BTCUSDT", "interval": "1h", "config": config},
            )
            assert response.status_code == 200, response.text
            return float(response.json()["stats"]["net_profit"])

        free = await net(maker_fee=0, taker_fee=0, slippage_bps=0, apply_funding=False)
        costed = await net(maker_fee=0.0002, taker_fee=0.0006, slippage_bps=1.0)
        assert costed < free

    async def test_reports_when_there_is_no_data(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/strategies", headers=headers, json=simple_strategy()
        )
        response = await client.post(
            f"{api_prefix}/strategies/{created.json()['id']}/backtest",
            headers=headers,
            json={"symbol": "NOTREAL", "interval": "1h"},
        )
        assert response.status_code == 422
        assert "No stored bars" in response.json()["detail"]

    async def test_rejects_an_unsupported_interval(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/strategies", headers=headers, json=simple_strategy()
        )
        response = await client.post(
            f"{api_prefix}/strategies/{created.json()['id']}/backtest",
            headers=headers,
            json={"symbol": "BTCUSDT", "interval": "7m"},
        )
        assert response.status_code == 422

    async def test_run_history_and_csv_export(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed_bars(db)
        created = await client.post(
            f"{api_prefix}/strategies", headers=headers, json=simple_strategy()
        )
        strategy_id = created.json()["id"]

        run = await client.post(
            f"{api_prefix}/strategies/{strategy_id}/backtest",
            headers=headers,
            json={"symbol": "BTCUSDT", "interval": "1h"},
        )
        run_id = run.json()["id"]

        history = await client.get(
            f"{api_prefix}/strategies/{strategy_id}/backtests", headers=headers
        )
        assert history.status_code == 200
        assert len(history.json()) == 1

        csv = await client.get(f"{api_prefix}/backtests/{run_id}/trades.csv", headers=headers)
        assert csv.status_code == 200
        assert csv.headers["content-type"].startswith("text/csv")
        lines = csv.text.strip().splitlines()
        assert lines[0].startswith("side,entry_time,entry_price")
        assert len(lines) == len(run.json()["trades"]) + 1

    async def test_a_run_belongs_to_its_owner(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed_bars(db)
        created = await client.post(
            f"{api_prefix}/strategies", headers=headers, json=simple_strategy()
        )
        run = await client.post(
            f"{api_prefix}/strategies/{created.json()['id']}/backtest",
            headers=headers,
            json={"symbol": "BTCUSDT", "interval": "1h"},
        )
        run_id = run.json()["id"]

        await register(client, api_prefix, email="intruder@example.com")
        tokens = await login(client, api_prefix, email="intruder@example.com")
        intruder = {"Authorization": f"Bearer {tokens['access_token']}"}

        assert (
            await client.get(f"{api_prefix}/backtests/{run_id}", headers=intruder)
        ).status_code == 404
        assert (
            await client.get(f"{api_prefix}/backtests/{run_id}/trades.csv", headers=intruder)
        ).status_code == 404
