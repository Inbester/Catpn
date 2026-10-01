"""Choosing a route, and alerts actually taking it (SPEC §3.6, §9).

These run with the app's runtime set the way main.py sets it at boot —
a live notifier and a tunnel manager — with the fake wireproxy standing in
for the real one, and an HTTP server on loopback standing in for a webhook
receiver. Whether a message went through a tunnel is read from the fake
proxy's own connection log, not inferred from what the app reports.
"""

from __future__ import annotations

import http.server
import json
import sys
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.api.network_runtime import set_runtime
from quanta.models.network import FeatureRoute, Tunnel
from quanta.services import routing
from quanta.services.alert_runner import run_once
from quanta.services.notifier import Notifier
from quanta.services.tunnels import TunnelManager, seal_config
from tests.test_alerts import alert_row, seed_rising
from tests.test_forward_routes import auth
from tests.test_tunnels import FAKE
from tests.test_wireguard import GOOD

BROKEN = GOOD.replace("vpn.example.net", "fail.invalid")
# Starts and listens, then carries nothing: the common real failure.
SILENT = GOOD.replace("vpn.example.net", "silent.invalid")


class Receiver:
    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        self.url = ""


@pytest.fixture
def receiver() -> Iterator[Receiver]:
    """A webhook endpoint on loopback that records what it was sent."""
    seen = Receiver()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(length))
            if self.path != "/hook":
                self.send_response(404)
                self.end_headers()
                return
            seen.bodies.append(body)
            self.send_response(204)
            self.end_headers()

        def do_GET(self) -> None:
            body = b"ip=203.0.113.50\n"
            self.send_response(200)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    seen.url = f"http://127.0.0.1:{server.server_address[1]}/hook"
    yield seen
    server.shutdown()


def logged(path: Path) -> str:
    """What the fake proxy connected to."""
    return path.read_text()


@pytest.fixture
def connects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "connects.log"
    log.touch()
    monkeypatch.setenv("FAKE_WIREPROXY_CONNECTS", str(log))
    return log


@pytest.fixture
async def runtime(tmp_path: Path) -> AsyncIterator[tuple[TunnelManager, Notifier]]:
    manager = TunnelManager(
        command=[sys.executable, str(FAKE)], runtime_dir=tmp_path / "run", startup_timeout=5.0
    )
    notifier = Notifier(live=True)
    set_runtime(manager, notifier)
    yield manager, notifier
    await manager.stop_all()
    await notifier.aclose()
    set_runtime(None, None)


async def add_tunnel(
    db: AsyncSession, user_id: uuid.UUID, label: str, config: str = GOOD, *, enabled: bool = True
) -> Tunnel:
    tunnel = Tunnel(
        user_id=user_id,
        label=label,
        secret=seal_config(config),
        summary={},
        enabled=enabled,
        priority=0,
        last_result={},
    )
    db.add(tunnel)
    await db.flush()
    return tunnel


async def route(db: AsyncSession, user_id: uuid.UUID, feature: str, *tunnels: Tunnel) -> None:
    db.add(FeatureRoute(user_id=user_id, feature=feature, tunnel_ids=[str(t.id) for t in tunnels]))
    await db.flush()


async def me(client: AsyncClient, api_prefix: str) -> tuple[dict[str, str], uuid.UUID]:
    headers = await auth(client, api_prefix)
    body = (await client.get(f"{api_prefix}/users/me", headers=headers)).json()
    return headers, uuid.UUID(body["id"])


class TestResolve:
    async def test_exchange_traffic_can_never_be_resolved_to_a_tunnel(
        self, db: AsyncSession
    ) -> None:
        # The second lock: the routes API refuses these, and so does this.
        for feature in ("bot", "chart_data", "research_download"):
            with pytest.raises(ValueError, match="may not be routed"):
                await routing.resolve(db, None, uuid.uuid4(), feature)

    async def test_an_unknown_feature_is_refused(self, db: AsyncSession) -> None:
        with pytest.raises(ValueError, match="not a routable feature"):
            await routing.resolve(db, None, uuid.uuid4(), "everything")

    async def test_no_route_means_the_server(self, db: AsyncSession) -> None:
        chosen = await routing.resolve(db, None, uuid.uuid4(), "alerts_delivery")
        assert chosen.proxy is None
        assert chosen.via == "server"
        assert chosen.note == ""

    async def test_the_first_working_tunnel_wins_and_the_skip_is_explained(
        self,
        client: AsyncClient,
        api_prefix: str,
        db: AsyncSession,
        runtime: tuple[TunnelManager, Notifier],
    ) -> None:
        manager, _ = runtime
        _, user_id = await me(client, api_prefix)
        off = await add_tunnel(db, user_id, "Office", enabled=False)
        broken = await add_tunnel(db, user_id, "Broken", BROKEN)
        home = await add_tunnel(db, user_id, "Home")
        await route(db, user_id, "alerts_delivery", off, broken, home)

        chosen = await routing.resolve(db, manager, user_id, "alerts_delivery")
        assert chosen.via == "Home"
        assert chosen.proxy is not None and chosen.proxy.startswith("socks5h://127.0.0.1:")
        assert "Office is switched off" in chosen.note
        assert "Broken is down" in chosen.note
        assert "no such host" in chosen.note

    async def test_when_every_tunnel_is_down_it_falls_back_to_the_server(
        self,
        client: AsyncClient,
        api_prefix: str,
        db: AsyncSession,
        runtime: tuple[TunnelManager, Notifier],
    ) -> None:
        manager, _ = runtime
        _, user_id = await me(client, api_prefix)
        broken = await add_tunnel(db, user_id, "Broken", BROKEN)
        await route(db, user_id, "alerts_delivery", broken)

        chosen = await routing.resolve(db, manager, user_id, "alerts_delivery")
        assert chosen.proxy is None
        assert chosen.via == "server"
        assert chosen.note.endswith("sent from the server instead")

    async def test_another_users_tunnel_is_never_used(
        self,
        client: AsyncClient,
        api_prefix: str,
        db: AsyncSession,
        runtime: tuple[TunnelManager, Notifier],
    ) -> None:
        from tests.test_research_routes import other_user

        manager, _ = runtime
        _, owner_id = await me(client, api_prefix)
        theirs = await other_user(client, api_prefix)
        their_id = uuid.UUID(
            (await client.get(f"{api_prefix}/users/me", headers=theirs)).json()["id"]
        )
        tunnel = await add_tunnel(db, owner_id, "Owner's")
        # A route row naming someone else's tunnel cannot be made through
        # the API; this is the resolver's own check if one ever existed.
        await route(db, their_id, "alerts_delivery", tunnel)

        chosen = await routing.resolve(db, manager, their_id, "alerts_delivery")
        assert chosen.proxy is None
        assert manager.state(str(tunnel.id)) == "stopped"


class TestAlertsTakeTheRoute:
    async def test_a_fired_alert_is_delivered_through_the_chosen_tunnel(
        self,
        client: AsyncClient,
        api_prefix: str,
        db: AsyncSession,
        runtime: tuple[TunnelManager, Notifier],
        receiver: Receiver,
        connects: Path,
    ) -> None:
        manager, notifier = runtime
        _, user_id = await me(client, api_prefix)
        # 22 bars: the last closes at 100.5 from 100.0, crossing the level.
        await seed_rising(db, count=22)
        home = await add_tunnel(db, user_id, "Home")
        await route(db, user_id, "alerts_delivery", home)
        db.add(alert_row(user_id, destinations=[{"kind": "webhook", "target": receiver.url}]))
        await db.commit()

        events = await run_once(db, notifier, tunnels=manager)

        assert events, "the seeded bars should fire the alert"
        delivery = events[0].deliveries[0]
        assert delivery["state"] == "sent", delivery
        assert delivery["route"] == "Home"
        assert len(receiver.bodies) == 1
        # The proxy itself saw the connection: it really went through.
        assert receiver.url.split("/")[2] in logged(connects)

    async def test_a_tunnel_that_carries_nothing_fails_over_to_the_next(
        self,
        client: AsyncClient,
        api_prefix: str,
        db: AsyncSession,
        runtime: tuple[TunnelManager, Notifier],
        receiver: Receiver,
        connects: Path,
    ) -> None:
        # The process is up, so nothing at start time says it is dead;
        # only the send finds out. The alert must still arrive, once.
        manager, notifier = runtime
        _, user_id = await me(client, api_prefix)
        await seed_rising(db, count=22)
        silent = await add_tunnel(db, user_id, "Silent", SILENT)
        home = await add_tunnel(db, user_id, "Home")
        await route(db, user_id, "alerts_delivery", silent, home)
        db.add(alert_row(user_id, destinations=[{"kind": "webhook", "target": receiver.url}]))
        await db.commit()

        events = await run_once(db, notifier, tunnels=manager)

        delivery = events[0].deliveries[0]
        assert delivery["state"] == "sent", delivery
        assert delivery["route"] == "Home"
        assert "Silent carried nothing recently" in delivery["note"]
        assert len(receiver.bodies) == 1
        assert manager.state(str(silent.id)) == "failed"
        assert "handshake" in (manager.last_error(str(silent.id)) or "")

        # And the next resolve skips it without trying it again.
        chosen = await routing.resolve(db, manager, user_id, "alerts_delivery")
        assert chosen.via == "Home"

    async def test_when_the_only_tunnel_carries_nothing_the_server_sends_it(
        self,
        client: AsyncClient,
        api_prefix: str,
        db: AsyncSession,
        runtime: tuple[TunnelManager, Notifier],
        receiver: Receiver,
        connects: Path,
    ) -> None:
        manager, notifier = runtime
        _, user_id = await me(client, api_prefix)
        await seed_rising(db, count=22)
        silent = await add_tunnel(db, user_id, "Silent", SILENT)
        await route(db, user_id, "alerts_delivery", silent)
        db.add(alert_row(user_id, destinations=[{"kind": "webhook", "target": receiver.url}]))
        await db.commit()

        events = await run_once(db, notifier, tunnels=manager)

        delivery = events[0].deliveries[0]
        assert delivery["state"] == "sent", delivery
        assert delivery["route"] == "server"
        assert delivery["note"].endswith("sent from the server instead")
        assert len(receiver.bodies) == 1

    async def test_a_destination_that_refuses_is_not_sent_twice(
        self,
        client: AsyncClient,
        api_prefix: str,
        db: AsyncSession,
        runtime: tuple[TunnelManager, Notifier],
        receiver: Receiver,
    ) -> None:
        # A 404 is the destination's answer, not the tunnel's fault; every
        # route would get the same answer, so it is not retried.
        manager, notifier = runtime
        _, user_id = await me(client, api_prefix)
        home = await add_tunnel(db, user_id, "Home")
        await route(db, user_id, "alerts_delivery", home)
        await db.commit()

        deliveries = await routing.deliver(
            db,
            notifier,
            manager,
            user_id,
            [{"kind": "webhook", "target": receiver.url.replace("/hook", "/missing")}],
            "hi",
        )
        assert deliveries[0].state == "failed"
        assert deliveries[0].route == "Home"
        assert manager.unreachable(str(home.id)) is None

    async def test_without_a_route_the_alert_goes_direct(
        self,
        client: AsyncClient,
        api_prefix: str,
        db: AsyncSession,
        runtime: tuple[TunnelManager, Notifier],
        receiver: Receiver,
        connects: Path,
    ) -> None:
        manager, notifier = runtime
        _, user_id = await me(client, api_prefix)
        # 22 bars: the last closes at 100.5 from 100.0, crossing the level.
        await seed_rising(db, count=22)
        db.add(alert_row(user_id, destinations=[{"kind": "webhook", "target": receiver.url}]))
        await db.commit()

        events = await run_once(db, notifier, tunnels=manager)

        assert events[0].deliveries[0]["route"] == "server"
        assert len(receiver.bodies) == 1
        assert logged(connects) == ""

    async def test_a_test_send_takes_the_same_route_as_a_real_one(
        self,
        client: AsyncClient,
        api_prefix: str,
        db: AsyncSession,
        runtime: tuple[TunnelManager, Notifier],
        receiver: Receiver,
        connects: Path,
    ) -> None:
        # A test that takes a different path from a real firing tests
        # nothing the user cares about.
        headers, user_id = await me(client, api_prefix)
        home = await add_tunnel(db, user_id, "Home")
        await route(db, user_id, "alerts_delivery", home)
        alert = alert_row(user_id, destinations=[{"kind": "webhook", "target": receiver.url}])
        db.add(alert)
        await db.commit()

        response = await client.post(
            f"{api_prefix}/alerts/{alert.id}/test", headers=headers, json={}
        )
        assert response.status_code in (200, 201), response.text
        delivery = response.json()["deliveries"][0]
        assert delivery["state"] == "sent", delivery
        assert delivery["route"] == "Home"
        assert receiver.url.split("/")[2] in logged(connects)


class TestLiveNotifier:
    async def test_a_live_telegram_send_without_a_token_fails_and_says_why(self) -> None:
        # Recording it as sent would tell the user an alert arrived when
        # it went nowhere.
        notifier = Notifier(live=True)
        try:
            deliveries = await notifier.deliver([{"kind": "telegram", "target": "123"}], "hi")
        finally:
            await notifier.aclose()
        assert deliveries[0].state == "failed"
        assert "TELEGRAM_BOT_TOKEN" in deliveries[0].note


class TestNetworkApi:
    async def test_the_engine_reports_whether_tunnels_can_run(
        self, client: AsyncClient, api_prefix: str, runtime: tuple[TunnelManager, Notifier]
    ) -> None:
        headers = await auth(client, api_prefix)
        body = (await client.get(f"{api_prefix}/network/engine", headers=headers)).json()
        assert body["available"] is True
        assert body["amnezia"] is False

    async def test_a_test_measures_the_tunnel_for_real(
        self,
        client: AsyncClient,
        api_prefix: str,
        runtime: tuple[TunnelManager, Notifier],
        receiver: Receiver,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from quanta.core.config import get_settings

        monkeypatch.setattr(get_settings(), "tunnel_probe_url", receiver.url)
        headers = await auth(client, api_prefix)
        created = (
            await client.post(
                f"{api_prefix}/network/tunnels",
                headers=headers,
                json={"label": "Home", "config": GOOD},
            )
        ).json()
        result = (
            await client.post(f"{api_prefix}/network/tunnels/{created['id']}/test", headers=headers)
        ).json()
        assert result["state"] == "ok", result
        assert result["exit_ip"] == "203.0.113.50"
        assert result["loss_percent"] == 0
        assert result["quality"] in {"good", "fair"}

        listed = (await client.get(f"{api_prefix}/network/tunnels", headers=headers)).json()
        assert listed[0]["state"] == "running"
        assert listed[0]["last_result"]["exit_ip"] == "203.0.113.50"

    async def test_a_tunnel_that_fails_shows_the_reason(
        self, client: AsyncClient, api_prefix: str, runtime: tuple[TunnelManager, Notifier]
    ) -> None:
        headers = await auth(client, api_prefix)
        created = (
            await client.post(
                f"{api_prefix}/network/tunnels",
                headers=headers,
                json={"label": "Broken", "config": BROKEN},
            )
        ).json()
        result = (
            await client.post(f"{api_prefix}/network/tunnels/{created['id']}/test", headers=headers)
        ).json()
        assert result["state"] == "failed"
        assert "no such host" in result["detail"]
        listed = (await client.get(f"{api_prefix}/network/tunnels", headers=headers)).json()
        assert listed[0]["state"] == "failed"
        assert "no such host" in listed[0]["last_error"]

    async def test_switching_a_tunnel_off_stops_it(
        self,
        client: AsyncClient,
        api_prefix: str,
        runtime: tuple[TunnelManager, Notifier],
        receiver: Receiver,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from quanta.core.config import get_settings

        monkeypatch.setattr(get_settings(), "tunnel_probe_url", receiver.url)
        manager, _ = runtime
        headers = await auth(client, api_prefix)
        created = (
            await client.post(
                f"{api_prefix}/network/tunnels",
                headers=headers,
                json={"label": "Home", "config": GOOD},
            )
        ).json()
        await client.post(f"{api_prefix}/network/tunnels/{created['id']}/test", headers=headers)
        assert manager.state(created["id"]) == "running"

        patched = await client.patch(
            f"{api_prefix}/network/tunnels/{created['id']}",
            headers=headers,
            json={"enabled": False},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["state"] == "off"
        assert manager.proxy_for(created["id"]) is None

    async def test_removing_a_tunnel_stops_it_and_drops_it_from_routes(
        self,
        client: AsyncClient,
        api_prefix: str,
        runtime: tuple[TunnelManager, Notifier],
        receiver: Receiver,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from quanta.core.config import get_settings

        monkeypatch.setattr(get_settings(), "tunnel_probe_url", receiver.url)
        manager, _ = runtime
        headers = await auth(client, api_prefix)
        created = (
            await client.post(
                f"{api_prefix}/network/tunnels",
                headers=headers,
                json={"label": "Home", "config": GOOD},
            )
        ).json()
        await client.put(
            f"{api_prefix}/network/routes",
            headers=headers,
            json={"feature": "alerts_delivery", "tunnel_ids": [created["id"]]},
        )
        await client.post(f"{api_prefix}/network/tunnels/{created['id']}/test", headers=headers)

        removed = await client.delete(
            f"{api_prefix}/network/tunnels/{created['id']}", headers=headers
        )
        assert removed.status_code == 204
        assert manager.proxy_for(created["id"]) is None
        routes = (await client.get(f"{api_prefix}/network/routes", headers=headers)).json()
        assert routes["alerts_delivery"] == []

    async def test_a_route_may_not_name_a_tunnel_twice(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        created = (
            await client.post(
                f"{api_prefix}/network/tunnels",
                headers=headers,
                json={"label": "Home", "config": GOOD},
            )
        ).json()
        response = await client.put(
            f"{api_prefix}/network/routes",
            headers=headers,
            json={"feature": "alerts_delivery", "tunnel_ids": [created["id"], created["id"]]},
        )
        assert response.status_code == 422

    async def test_importing_an_amnezia_config_warns_when_it_cannot_run(
        self, client: AsyncClient, api_prefix: str, runtime: tuple[TunnelManager, Notifier]
    ) -> None:
        headers = await auth(client, api_prefix)
        amnezia = GOOD.replace("DNS = 1.1.1.1", "DNS = 1.1.1.1\nJc = 4\nH1 = 1234")
        body = (
            await client.post(
                f"{api_prefix}/network/validate", headers=headers, json={"config": amnezia}
            )
        ).json()
        assert any("AmneziaWG" in warning for warning in body["warnings"])
