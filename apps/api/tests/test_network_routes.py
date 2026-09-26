"""Tunnel import, testing and what may be routed (SPEC §3.6, §9)."""

from __future__ import annotations

from httpx import AsyncClient

from tests.test_forward_routes import auth
from tests.test_wireguard import GOOD


class TestImport:
    async def test_a_good_config_imports_and_hides_its_key(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/network/tunnels",
            headers=headers,
            json={"label": "Home", "config": GOOD},
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["summary"]["endpoint"] == "vpn.example.net:51820"
        # SPEC §3.6: the private key is encrypted at rest and never shown.
        assert "aFmSs7" not in created.text

        listed = await client.get(f"{api_prefix}/network/tunnels", headers=headers)
        assert "aFmSs7" not in listed.text
        assert len(listed.json()) == 1

    async def test_a_bad_config_is_refused_with_the_reason(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/network/tunnels",
            headers=headers,
            json={"label": "Broken", "config": "[Interface]\nPrivateKey = nope\n"},
        )
        assert response.status_code == 422
        assert "[Peer]" in response.json()["detail"]

    async def test_validate_checks_without_storing(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/network/validate", headers=headers, json={"config": GOOD}
        )
        assert response.json()["valid"] is True
        assert (await client.get(f"{api_prefix}/network/tunnels", headers=headers)).json() == []

    async def test_a_tunnel_is_private_to_its_owner(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        from tests.test_research_routes import other_user

        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/network/tunnels",
            headers=headers,
            json={"label": "Home", "config": GOOD},
        )
        theirs = await other_user(client, api_prefix)
        assert (await client.get(f"{api_prefix}/network/tunnels", headers=theirs)).json() == []
        assert (
            await client.delete(
                f"{api_prefix}/network/tunnels/{created.json()['id']}", headers=theirs
            )
        ).status_code == 404


class TestRoutingLimits:
    async def test_the_locked_features_are_listed_with_their_reasons(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        # Returned rather than omitted: a control that is silently absent
        # looks like a missing feature, and the reason is what is needed.
        headers = await auth(client, api_prefix)
        body = (await client.get(f"{api_prefix}/network/features", headers=headers)).json()
        assert set(body["locked"]) == {"chart_data", "research_download", "bot"}
        assert all(body["locked"].values())

    async def test_market_data_cannot_be_routed_through_a_personal_exit(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        # SPEC §9: the product must not be used to reach a venue from a
        # region it restricts.
        headers = await auth(client, api_prefix)
        response = await client.put(
            f"{api_prefix}/network/routes",
            headers=headers,
            json={"feature": "chart_data", "tunnel_ids": []},
        )
        assert response.status_code == 422
        assert "SPEC §9" in response.json()["detail"]

    async def test_bot_orders_cannot_be_routed(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        response = await client.put(
            f"{api_prefix}/network/routes",
            headers=headers,
            json={"feature": "bot", "tunnel_ids": []},
        )
        assert response.status_code == 422
        assert "static IP" in response.json()["detail"]

    async def test_alert_delivery_may_be_routed(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/network/tunnels",
            headers=headers,
            json={"label": "Home", "config": GOOD},
        )
        response = await client.put(
            f"{api_prefix}/network/routes",
            headers=headers,
            json={"feature": "alerts_delivery", "tunnel_ids": [created.json()["id"]]},
        )
        assert response.status_code == 200, response.text
        routes = (await client.get(f"{api_prefix}/network/routes", headers=headers)).json()
        assert routes["alerts_delivery"] == [created.json()["id"]]

    async def test_routing_to_a_tunnel_you_do_not_own_is_refused(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        from tests.test_research_routes import other_user

        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/network/tunnels",
            headers=headers,
            json={"label": "Home", "config": GOOD},
        )
        theirs = await other_user(client, api_prefix)
        response = await client.put(
            f"{api_prefix}/network/routes",
            headers=theirs,
            json={"feature": "ai", "tunnel_ids": [created.json()["id"]]},
        )
        assert response.status_code == 404


class TestTesting:
    async def test_a_test_reports_unavailable_rather_than_inventing_bars(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        # A quality bar invented from nothing is worse than no bar,
        # because it will be believed.
        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/network/tunnels",
            headers=headers,
            json={"label": "Home", "config": GOOD},
        )
        response = await client.post(
            f"{api_prefix}/network/tunnels/{created.json()['id']}/test", headers=headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"] == "unavailable"
        assert body["quality"] is None
        assert body["latency_ms"] is None

    async def test_tests_are_rate_limited(self, client: AsyncClient, api_prefix: str) -> None:
        # A page left open must not become a probe.
        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/network/tunnels",
            headers=headers,
            json={"label": "Home", "config": GOOD},
        )
        url = f"{api_prefix}/network/tunnels/{created.json()['id']}/test"
        assert (await client.post(url, headers=headers)).status_code == 200
        assert (await client.post(url, headers=headers)).status_code == 429
