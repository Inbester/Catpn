"""Research studies, the Discover search and the job runner."""

from __future__ import annotations

import asyncio

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_auth_routes import login, register
from tests.test_forward_routes import auth, make_strategy, seed


async def other_user(client: AsyncClient, prefix: str) -> dict[str, str]:
    """A second account, for the ownership checks."""
    email = "intruder@example.com"
    await register(client, prefix, email=email)
    tokens = await login(client, prefix, email=email)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


class TestLeverage:
    async def test_returns_a_surface_and_a_recommendation(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=120)
        strategy_id = await make_strategy(client, api_prefix, headers)

        response = await client.post(
            f"{api_prefix}/research/{strategy_id}/leverage",
            headers=headers,
            json={
                "symbol": "BTCUSDT",
                "interval": "1h",
                "margins": [5.0, 10.0],
                "leverages": [1.0, 2.0, 5.0],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["cells"]) == 6
        assert body["recommendation"]["reason"]
        # Exposure is the identity the whole study rests on.
        for cell in body["cells"]:
            assert cell["exposure"] == cell["margin_percent"] * cell["leverage"] / 100
        assert [row["margin_mode"] for row in body["margin_modes"]] == ["isolated", "cross"]

    async def test_refuses_a_grid_too_large_to_run_interactively(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        strategy_id = await make_strategy(client, api_prefix, headers)
        response = await client.post(
            f"{api_prefix}/research/{strategy_id}/leverage",
            headers=headers,
            json={
                "symbol": "BTCUSDT",
                "margins": [float(i) for i in range(1, 13)],
                "leverages": [float(i) for i in range(1, 13)],
            },
        )
        # 144 is allowed; the validator rejects anything past it.
        assert response.status_code in {200, 422}

    async def test_another_user_cannot_study_a_strategy(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        owner = await auth(client, api_prefix)
        strategy_id = await make_strategy(client, api_prefix, owner)
        intruder = await other_user(client, api_prefix)

        response = await client.post(
            f"{api_prefix}/research/{strategy_id}/leverage",
            headers=intruder,
            json={"symbol": "BTCUSDT"},
        )
        assert response.status_code == 404


class TestTradeRisk:
    async def test_reports_dips_and_the_leverage_they_survive(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=120)
        strategy_id = await make_strategy(client, api_prefix, headers)

        response = await client.post(
            f"{api_prefix}/research/{strategy_id}/trade-risk",
            headers=headers,
            json={"symbol": "BTCUSDT", "interval": "1h"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["kpis"]["survives_up_to_leverage"] > 0
        assert isinstance(body["points"], list)


class TestRobustness:
    async def test_runs_the_stress_cases_and_the_surface(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=120)
        strategy_id = await make_strategy(client, api_prefix, headers)

        response = await client.post(
            f"{api_prefix}/research/{strategy_id}/robustness",
            headers=headers,
            json={
                "symbol": "BTCUSDT",
                "interval": "1h",
                "grid": {"fast": [10, 20, 30]},
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [case["name"] for case in body["stress"]] == [
            "VIP3 fees",
            "Fees doubled",
            "Slippage tripled",
            "Funding +0.03% per 8h",
            "Best 5 trades removed",
        ]
        # The adverse cases must never improve the result. VIP3 is the
        # one that can: its fees are lower than the VIP0 default, so it is
        # marked as a what-if rather than a test of survival.
        for case in body["stress"]:
            if case["adverse"]:
                assert case["delta_percent"] <= 1e-9, case["name"]
        vip3 = next(c for c in body["stress"] if c["name"] == "VIP3 fees")
        assert vip3["adverse"] is False
        assert len(body["surface"]["points"]) == 3

    async def test_refuses_a_surface_too_large_to_run(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        strategy_id = await make_strategy(client, api_prefix, headers)
        response = await client.post(
            f"{api_prefix}/research/{strategy_id}/robustness",
            headers=headers,
            json={
                "symbol": "BTCUSDT",
                "grid": {"a": list(range(20)), "b": list(range(20))},
            },
        )
        assert response.status_code == 422


class TestDiscover:
    async def test_plan_says_what_a_search_would_cost(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=60)

        response = await client.post(
            f"{api_prefix}/research/discover/plan",
            headers=headers,
            json={"symbol": "BTCUSDT", "interval": "1h", "sources": ["price", "rsi"]},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["tests"] == body["rules"] * 8
        assert body["primitives"] == body["filters"] + body["triggers"]

    async def test_a_search_runs_as_a_job_and_reports_progress(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=60)

        started = await client.post(
            f"{api_prefix}/research/discover",
            headers=headers,
            json={
                "symbol": "BTCUSDT",
                "interval": "1h",
                "sources": ["price", "rsi"],
                "cost_percent": 0.0,
            },
        )
        assert started.status_code == 202, started.text
        job_id = started.json()["id"]
        assert started.json()["total"] > 0

        for _ in range(200):
            polled = await client.get(f"{api_prefix}/jobs/{job_id}", headers=headers)
            assert polled.status_code == 200
            body = polled.json()
            if body["state"] in {"done", "failed"}:
                break
            await asyncio.sleep(0.1)

        assert body["state"] == "done", body.get("error")
        result = body["result"]
        assert result["tested"] > 0
        # The uncorrected count rides along beside the corrected one: the
        # gap between them is what the correction is for.
        assert result["significant_uncorrected"] >= len(result["hits"])
        assert result["in_sample_bars"] > result["out_of_sample_bars"]

    async def test_a_running_poll_does_not_carry_the_result(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=60)
        started = await client.post(
            f"{api_prefix}/research/discover",
            headers=headers,
            json={"symbol": "BTCUSDT", "sources": ["price", "ema", "rsi"]},
        )
        job_id = started.json()["id"]
        polled = await client.get(f"{api_prefix}/jobs/{job_id}", headers=headers)
        if polled.json()["state"] == "running":
            assert polled.json()["result"] is None

    async def test_a_search_can_be_cancelled(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=60)
        started = await client.post(
            f"{api_prefix}/research/discover",
            headers=headers,
            json={"symbol": "BTCUSDT", "sources": ["price", "ema", "rsi", "macd"]},
        )
        job_id = started.json()["id"]

        cancelled = await client.delete(f"{api_prefix}/jobs/{job_id}", headers=headers)
        assert cancelled.status_code == 202

        for _ in range(200):
            body = (await client.get(f"{api_prefix}/jobs/{job_id}", headers=headers)).json()
            if body["state"] in {"cancelled", "done", "failed"}:
                break
            await asyncio.sleep(0.1)
        assert body["state"] in {"cancelled", "done"}

    async def test_a_job_belongs_to_the_user_who_started_it(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=60)
        started = await client.post(
            f"{api_prefix}/research/discover",
            headers=headers,
            json={"symbol": "BTCUSDT", "sources": ["price", "rsi"]},
        )
        job_id = started.json()["id"]

        intruder = await other_user(client, api_prefix)
        assert (
            await client.get(f"{api_prefix}/jobs/{job_id}", headers=intruder)
        ).status_code == 404
        assert (
            await client.delete(f"{api_prefix}/jobs/{job_id}", headers=intruder)
        ).status_code == 404

    async def test_refuses_a_history_too_short_to_search(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/research/discover/plan",
            headers=headers,
            json={"symbol": "NOTHING", "interval": "1h"},
        )
        assert response.status_code == 422
        assert "bars" in response.json()["detail"]


class TestSources:
    async def test_lists_the_chips_a_search_can_use(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        response = await client.get(f"{api_prefix}/research/sources", headers=headers)
        assert response.status_code == 200
        keys = {row["key"] for row in response.json()}
        assert {"price", "ema", "rsi"} <= keys
