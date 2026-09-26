"""Compute routing, its locks, and jobs that survive a restart."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.services import jobs
from tests.test_forward_routes import auth, seed


class TestComputePreferences:
    async def test_starts_from_the_documented_defaults(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        response = await client.get(f"{api_prefix}/compute", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["routing"]["research"] == "auto"
        assert body["routing"]["alerts"] == "server"
        assert body["server"]["cpu_cores"] >= 1

    async def test_research_can_be_moved_to_the_browser(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        response = await client.put(
            f"{api_prefix}/compute", headers=headers, json={"routing": {"research": "local"}}
        )
        assert response.status_code == 200, response.text
        assert response.json()["routing"]["research"] == "local"

    async def test_alerts_cannot_leave_the_server(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        # Refused rather than silently corrected: someone who asked for
        # alerts on their laptop should be told why they cannot have it.
        headers = await auth(client, api_prefix)
        response = await client.put(
            f"{api_prefix}/compute", headers=headers, json={"routing": {"alerts": "local"}}
        )
        assert response.status_code == 422
        assert "browser is closed" in response.json()["detail"]

    async def test_bot_orders_cannot_leave_the_server(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        # SPEC §9: the exchange API key is whitelisted to the server's
        # static IP, and routing orders elsewhere would break it.
        headers = await auth(client, api_prefix)
        response = await client.put(
            f"{api_prefix}/compute", headers=headers, json={"routing": {"bot": "auto"}}
        )
        assert response.status_code == 422
        assert "static IP" in response.json()["detail"]

    async def test_refuses_an_unknown_feature_or_source(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        assert (
            await client.put(
                f"{api_prefix}/compute", headers=headers, json={"routing": {"mining": "local"}}
            )
        ).status_code == 422
        assert (
            await client.put(
                f"{api_prefix}/compute", headers=headers, json={"routing": {"research": "moon"}}
            )
        ).status_code == 422

    async def test_allocation_and_device_details_persist(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        await client.put(
            f"{api_prefix}/compute",
            headers=headers,
            json={
                "cpu_share_percent": 75,
                "ram_budget_mb": 4096,
                "device_label": "Workshop iMac",
                "local_profile": {"cores": 10, "webgpu": True},
            },
        )
        body = (await client.get(f"{api_prefix}/compute", headers=headers)).json()
        assert body["cpu_share_percent"] == 75
        assert body["ram_budget_mb"] == 4096
        assert body["device_label"] == "Workshop iMac"
        assert body["local_profile"]["webgpu"] is True

    async def test_preferences_are_per_user(self, client: AsyncClient, api_prefix: str) -> None:
        from tests.test_research_routes import other_user

        mine = await auth(client, api_prefix)
        await client.put(
            f"{api_prefix}/compute", headers=mine, json={"routing": {"research": "local"}}
        )
        theirs = await other_user(client, api_prefix)
        body = (await client.get(f"{api_prefix}/compute", headers=theirs)).json()
        assert body["routing"]["research"] == "auto"


class TestJobHistory:
    async def test_a_started_job_is_recorded(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await seed(db, days=60)
        started = await client.post(
            f"{api_prefix}/research/discover",
            headers=headers,
            json={"symbol": "BTCUSDT", "sources": ["price", "rsi"]},
        )
        assert started.status_code == 202

        history = await client.get(f"{api_prefix}/jobs/history", headers=headers)
        assert history.status_code == 200, history.text
        rows = history.json()
        assert any(row["id"] == started.json()["id"] for row in rows)
        row = next(r for r in rows if r["id"] == started.json()["id"])
        # The stored request is what makes running it again possible.
        assert row["request"]["symbol"] == "BTCUSDT"

    async def test_a_restart_closes_out_jobs_left_running(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        # Without this a killed process leaves rows claiming to run
        # forever, and the rail counts progress nothing is making.
        headers = await auth(client, api_prefix)
        await seed(db, days=60)
        await client.post(
            f"{api_prefix}/research/discover",
            headers=headers,
            json={"symbol": "BTCUSDT", "sources": ["price", "ema", "rsi", "macd"]},
        )

        await jobs.mark_interrupted(db)
        rows = (await client.get(f"{api_prefix}/jobs/history", headers=headers)).json()
        assert all(row["state"] not in {"queued", "running"} for row in rows)

    async def test_history_is_private_to_its_owner(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        from tests.test_research_routes import other_user

        headers = await auth(client, api_prefix)
        await seed(db, days=60)
        await client.post(
            f"{api_prefix}/research/discover",
            headers=headers,
            json={"symbol": "BTCUSDT", "sources": ["price", "rsi"]},
        )
        theirs = await other_user(client, api_prefix)
        assert (await client.get(f"{api_prefix}/jobs/history", headers=theirs)).json() == []
