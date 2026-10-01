"""Running WireGuard tunnels as local proxies (SPEC §3.6).

Most of this runs against a fake wireproxy (tests/fixtures/fake_wireproxy.py)
that speaks SOCKS5 and connects directly, so the manager's behaviour —
start, fail with a reason, delete the key file, stop — is tested anywhere.
`TestRealWireproxy` runs the real binary end to end, two peers over a real
WireGuard handshake, when `WIREPROXY_TEST_BINARY` points at one.
"""

from __future__ import annotations

import asyncio
import http.server
import os
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from quanta.core.config import Settings
from quanta.services import tunnels
from quanta.services.tunnels import TunnelError, TunnelManager
from tests.test_wireguard import GOOD

FAKE = Path(__file__).parent / "fixtures" / "fake_wireproxy.py"

AMNEZIA = GOOD.replace("DNS = 1.1.1.1", "DNS = 1.1.1.1\nJc = 4\nJmin = 40\nJmax = 70\nH1 = 1234")
WG_QUICK = GOOD.replace(
    "DNS = 1.1.1.1",
    "DNS = 1.1.1.1\nPostUp = iptables -A FORWARD -j ACCEPT\nTable = off\nSaveConfig = true",
)


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def trace_server() -> Iterator[str]:
    """Answers like Cloudflare's trace endpoint, which is what probes read."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"fl=1\nip=203.0.113.50\nts=1\n"
            self.send_response(200)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/cdn-cgi/trace"
    server.shutdown()


@pytest.fixture
def manager(tmp_path: Path) -> TunnelManager:
    return TunnelManager(
        command=[sys.executable, str(FAKE)],
        runtime_dir=tmp_path / "run",
        startup_timeout=5.0,
    )


class TestRender:
    def test_wg_quick_host_commands_never_reach_wireproxy(self) -> None:
        # PostUp runs as root under wg-quick. Nothing in an imported file
        # should be able to ask the server to run a command.
        rendered = tunnels.render(WG_QUICK, port=40000)
        assert "PostUp" not in rendered
        assert "iptables" not in rendered
        assert "Table" not in rendered
        assert "SaveConfig" not in rendered

    def test_the_proxy_listens_on_loopback_only(self) -> None:
        rendered = tunnels.render(GOOD, port=40000)
        assert "[Socks5]\nBindAddress = 127.0.0.1:40000" in rendered

    def test_the_resolver_strategy_is_set_because_the_default_fails(self) -> None:
        assert "ResolveStrategy = ipv4" in tunnels.render(GOOD, port=40000)

    def test_a_config_without_dns_gets_public_resolvers(self) -> None:
        without = GOOD.replace("DNS = 1.1.1.1\n", "")
        assert not tunnels.has_dns(without)
        assert f"DNS = {tunnels.DEFAULT_DNS}" in tunnels.render(without, port=40000)

    def test_a_config_with_dns_keeps_its_own(self) -> None:
        rendered = tunnels.render(GOOD, port=40000)
        assert "DNS = 1.1.1.1" in rendered
        assert tunnels.DEFAULT_DNS not in rendered

    def test_the_wireguard_sections_survive(self) -> None:
        rendered = tunnels.render(GOOD, port=40000)
        assert "PrivateKey = aFmSs7" in rendered
        assert "Endpoint = vpn.example.net:51820" in rendered
        assert "PersistentKeepalive = 25" in rendered

    def test_amnezia_keys_are_kept_only_for_the_amnezia_build(self) -> None:
        assert "Jc = 4" not in tunnels.render(AMNEZIA, port=40000)
        assert "Jc = 4" in tunnels.render(AMNEZIA, port=40000, amnezia=True)

    def test_an_amnezia_config_is_recognised(self) -> None:
        assert tunnels.is_amnezia(AMNEZIA)
        assert not tunnels.is_amnezia(GOOD)


class TestSealing:
    def test_a_sealed_config_opens_and_does_not_show_its_key(self) -> None:
        settings = make_settings(vault_master_key="m" * 48)
        token = tunnels.seal_config(GOOD, settings)
        assert "aFmSs7" not in token
        assert tunnels.open_config(token, settings) == GOOD

    def test_the_session_secret_alone_cannot_open_it(self) -> None:
        # A leaked SECRET_KEY must not hand over WireGuard private keys.
        sealed = tunnels.seal_config(GOOD, make_settings(vault_master_key="m" * 48))
        with pytest.raises(TunnelError):
            tunnels.open_config(sealed, make_settings(vault_master_key="other" * 10))

    def test_configs_sealed_before_the_key_change_still_open(self) -> None:
        settings = make_settings(vault_master_key="m" * 48)
        legacy = tunnels._legacy_fernet(settings).encrypt(GOOD.encode()).decode()
        assert tunnels.open_config(legacy, settings) == GOOD


class TestBands:
    @pytest.mark.parametrize(
        ("latency", "loss", "expected"),
        [
            (None, 100.0, "down"),
            (80.0, 0.0, "good"),
            (200.0, 0.0, "fair"),
            (80.0, 33.3, "fair"),
            (450.0, 0.0, "poor"),
        ],
    )
    def test_measurements_band_to_one_word(
        self, latency: float | None, loss: float, expected: str
    ) -> None:
        assert tunnels.band(latency, loss) == expected


class TestProbe:
    async def test_a_reachable_route_reports_its_exit_ip_and_latency(
        self, trace_server: str
    ) -> None:
        result = await tunnels.probe(None, url=trace_server, attempts=3)
        assert result["state"] == "ok"
        assert result["exit_ip"] == "203.0.113.50"
        assert result["loss_percent"] == 0
        assert result["latency_ms"] is not None
        assert result["jitter_ms"] is not None
        assert result["quality"] in {"good", "fair"}

    async def test_an_unreachable_route_reports_failure_not_numbers(self) -> None:
        result = await tunnels.probe(
            "socks5h://127.0.0.1:9", url="http://127.0.0.1:9/", attempts=2, request_timeout=1
        )
        assert result["state"] == "failed"
        assert result["loss_percent"] == 100
        assert result["latency_ms"] is None
        assert result["quality"] == "down"
        assert "UDP" in result["detail"]

    async def test_a_proxy_that_never_answers_is_cut_off_at_the_deadline(self) -> None:
        # wireproxy holds the SOCKS exchange open while it waits on a peer
        # that never answers; httpx's own timeouts do not cover that part.
        async def hang(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.read(16)
            writer.write(b"\x05\x00")
            await asyncio.sleep(30)

        server = await asyncio.start_server(hang, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        started = asyncio.get_running_loop().time()
        async with server:
            result = await tunnels.probe(
                f"socks5h://127.0.0.1:{port}",
                url="http://10.77.0.1:8080/",
                attempts=3,
                request_timeout=0.5,
            )
            server.close()
        assert asyncio.get_running_loop().time() - started < 3
        assert result["state"] == "failed"
        assert "no answer within" in result["detail"]

    async def test_a_dead_route_is_reported_after_one_try_not_all(self) -> None:
        # Each try through a dead tunnel waits out wireproxy's handshake
        # timeout; the button must not make the user wait three of them.
        calls = 0

        async def count(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            nonlocal calls
            calls += 1
            writer.close()

        server = await asyncio.start_server(count, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            result = await tunnels.probe(
                f"socks5h://127.0.0.1:{port}", url="http://10.77.0.1:8080/", attempts=3
            )
        assert result["state"] == "failed"
        assert calls == 1

    async def test_a_tunnel_with_no_handshake_reports_failure_not_a_crash(self) -> None:
        # What wireproxy does when the peer never answers: it accepts the
        # SOCKS connection and then sends a reply that is not SOCKS. That
        # is not an httpx error, and once escaped the Test button as a 500.
        async def garbage(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.read(16)  # greeting
            writer.write(b"\x05\x00")
            await reader.read(64)  # connect request
            # "Host unreachable" with an address type SOCKS does not define.
            writer.write(b"\x05\x04\x00\x00")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(garbage, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            result = await tunnels.probe(
                f"socks5h://127.0.0.1:{port}", url="http://10.77.0.1:8080/", attempts=2
            )
        assert result["state"] == "failed"
        assert result["quality"] == "down"
        assert "handshake" in result["detail"]

    async def test_a_probe_ignores_proxy_variables_in_the_environment(
        self, trace_server: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # What is measured must be the route asked for, not whatever the
        # server's environment happens to say.
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
        monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        result = await tunnels.probe(None, url=trace_server, attempts=1)
        assert result["state"] == "ok"


class TestManager:
    async def test_a_tunnel_starts_and_carries_traffic(
        self, manager: TunnelManager, trace_server: str
    ) -> None:
        proxy = await manager.ensure("t1", GOOD)
        try:
            assert proxy.startswith("socks5h://127.0.0.1:")
            assert manager.state("t1") == "running"
            result = await tunnels.probe(proxy, url=trace_server, attempts=2)
            assert result["state"] == "ok"
            assert result["exit_ip"] == "203.0.113.50"
        finally:
            await manager.stop_all()

    async def test_ensuring_twice_reuses_the_running_tunnel(self, manager: TunnelManager) -> None:
        try:
            first = await manager.ensure("t1", GOOD)
            assert await manager.ensure("t1", GOOD) == first
        finally:
            await manager.stop_all()

    async def test_the_private_key_file_is_gone_once_the_proxy_listens(
        self, manager: TunnelManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = tmp_path / "seen.conf"
        monkeypatch.setenv("FAKE_WIREPROXY_SEEN", str(seen))
        try:
            await manager.ensure("t1", WG_QUICK)
            # The process got the key...
            assert "PrivateKey = aFmSs7" in seen.read_text()
            # ...but not the host commands, and nothing is left on disk.
            assert "PostUp" not in seen.read_text()
            assert list((tmp_path / "run").iterdir()) == []
        finally:
            await manager.stop_all()

    async def test_a_tunnel_that_will_not_start_says_why(
        self, manager: TunnelManager, tmp_path: Path
    ) -> None:
        broken = GOOD.replace("vpn.example.net", "fail.invalid")
        with pytest.raises(TunnelError, match="no such host"):
            await manager.ensure("t1", broken)
        assert manager.state("t1") == "failed"
        assert "no such host" in (manager.last_error("t1") or "")
        assert list((tmp_path / "run").iterdir()) == []

    async def test_a_later_success_clears_the_failure(self, manager: TunnelManager) -> None:
        with pytest.raises(TunnelError):
            await manager.ensure("t1", GOOD.replace("vpn.example.net", "fail.invalid"))
        try:
            await manager.ensure("t1", GOOD)
            assert manager.state("t1") == "running"
            assert manager.last_error("t1") is None
        finally:
            await manager.stop_all()

    async def test_stopping_closes_the_proxy(self, manager: TunnelManager) -> None:
        proxy = await manager.ensure("t1", GOOD)
        port = int(proxy.rsplit(":", 1)[1])
        await manager.stop("t1")
        assert manager.state("t1") == "stopped"
        assert manager.proxy_for("t1") is None
        with pytest.raises(OSError):
            await asyncio.open_connection("127.0.0.1", port)

    async def test_an_amnezia_config_is_refused_without_the_amnezia_build(
        self, manager: TunnelManager
    ) -> None:
        # Plain wireproxy accepts it and then never completes a handshake,
        # which looks like a tunnel that is up and carries nothing.
        with pytest.raises(TunnelError, match="AmneziaWG"):
            await manager.ensure("t1", AMNEZIA)

    async def test_an_amnezia_config_runs_on_the_amnezia_build(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = tmp_path / "seen.conf"
        monkeypatch.setenv("FAKE_WIREPROXY_SEEN", str(seen))
        manager = TunnelManager(
            command=["definitely-not-installed-wireproxy"],
            awg_command=[sys.executable, str(FAKE)],
            runtime_dir=tmp_path / "run",
        )
        try:
            await manager.ensure("t1", AMNEZIA)
            assert "Jc = 4" in seen.read_text()
        finally:
            await manager.stop_all()

    def test_a_missing_binary_is_reported_not_hidden(self, tmp_path: Path) -> None:
        manager = TunnelManager(command=["definitely-not-installed-wireproxy"])
        assert manager.available is False
        assert manager.engine()["available"] is False
        assert "not installed" in manager.engine()["detail"]
        assert manager.state("t1") == "unavailable"


REAL = os.environ.get("WIREPROXY_TEST_BINARY", "")

SERVER_PEER = """
[Interface]
PrivateKey = EGG3jJtkzn2Ni/upgdcus0y8cPH/hHqGINtZ/d6sBWs=
Address = 10.77.0.1/24
ListenPort = {listen}

[Peer]
PublicKey = U8JBacKgk2WroRc3A04k/2HZdpYCccvG1JkuZPjUESs=
AllowedIPs = 10.77.0.2/32

[TCPServerTunnel]
ListenPort = 8080
Target = 127.0.0.1:{target}
"""

CLIENT_PEER = """
[Interface]
PrivateKey = UDkgSyS2XBDPbLNB25t2EDfNHgpdFIOrox+OLMXESVM=
Address = 10.77.0.2/24
PostUp = touch {marker}

[Peer]
PublicKey = c4AUBnSeY5IWA+Gx1vL/jULjQRtTFwg8+leKkxpb7RQ=
Endpoint = 127.0.0.1:{listen}
AllowedIPs = 10.77.0.0/24
PersistentKeepalive = 5
"""


@pytest.mark.skipif(not REAL, reason="set WIREPROXY_TEST_BINARY to run against real wireproxy")
class TestRealWireproxy:
    async def test_traffic_crosses_a_real_wireguard_handshake(
        self, tmp_path: Path, trace_server: str
    ) -> None:
        # Peer A is a plain wireproxy forwarding 10.77.0.1:8080 to the
        # trace server; peer B is started by TunnelManager from a config
        # the way a user would paste it, wg-quick extras included.
        target = int(trace_server.split(":")[2].split("/")[0])
        listen = tunnels._free_port()
        server_conf = tmp_path / "server.conf"
        server_conf.write_text(SERVER_PEER.format(listen=listen, target=target))
        server = await asyncio.create_subprocess_exec(
            REAL,
            "-c",
            str(server_conf),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        marker = tmp_path / "postup-ran"
        manager = TunnelManager(command=[REAL], runtime_dir=tmp_path / "run")
        try:
            await asyncio.sleep(0.5)
            proxy = await manager.ensure("real", CLIENT_PEER.format(listen=listen, marker=marker))
            result = await tunnels.probe(
                proxy, url="http://10.77.0.1:8080/cdn-cgi/trace", attempts=3
            )
            assert result["state"] == "ok", result
            assert result["exit_ip"] == "203.0.113.50"
            # PostUp was stripped, so the host command never ran.
            assert not marker.exists()
        finally:
            await manager.stop_all()
            server.terminate()
            await server.wait()
