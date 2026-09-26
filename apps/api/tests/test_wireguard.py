"""WireGuard config validation (SPEC §3.6).

A config with a truncated key or a missing port fails at connect time
with a kernel message that tells the user nothing. These tests pin that
every such mistake is named before anything is saved.
"""

from __future__ import annotations

import pytest

from quanta.services.wireguard import mask_ip, parse, quality_band, summarise

# A well-formed config, used as the base every bad case deviates from.
GOOD = """
[Interface]
PrivateKey = aFmSs7VOaMkHbHLFTVGLb5UTQKlqRvXTkOPTOm1w0FI=
Address = 10.66.66.2/32, fd42:42::2/128
DNS = 1.1.1.1

[Peer]
PublicKey = xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg=
Endpoint = vpn.example.net:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""


class TestValidConfig:
    def test_a_good_config_parses(self) -> None:
        result = parse(GOOD)
        assert result.valid, result.errors
        assert result.config.endpoint_host == "vpn.example.net"
        assert result.config.endpoint_port == 51820
        assert result.config.keepalive == 25
        assert result.config.has_private_key is True

    def test_comments_and_blank_lines_are_ignored(self) -> None:
        text = GOOD.replace("[Peer]", "# a comment\n\n[Peer]")
        assert parse(text).valid

    def test_a_private_key_is_never_returned(self) -> None:
        # Recognised, checked for shape, and then not handed back.
        summary = summarise(parse(GOOD).config)
        assert "aFmSs7" not in str(summary)
        assert summary["public_key"].startswith("xTIBA5")


class TestMissingSections:
    def test_no_interface_section(self) -> None:
        result = parse("[Peer]\nPublicKey = x\n")
        assert result.valid is False
        assert any("[Interface]" in error for error in result.errors)

    def test_no_peer_section(self) -> None:
        result = parse("[Interface]\nPrivateKey = x\n")
        assert result.valid is False
        assert any("[Peer]" in error for error in result.errors)

    def test_an_empty_file(self) -> None:
        assert parse("").valid is False


class TestKeys:
    @pytest.mark.parametrize(
        "bad",
        [
            "tooshort",
            "aFmSs7VOaMkHbHLFTVGLb5UTQKlqRvXTkOPTOm1w0F",  # a character short
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!=",
        ],
    )
    def test_a_key_that_is_not_thirty_two_bytes_of_base64(self, bad: str) -> None:
        result = parse(GOOD.replace("xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg=", bad))
        assert result.valid is False
        assert any("base64" in error for error in result.errors)

    def test_a_preshared_key_is_checked_too(self) -> None:
        text = GOOD.replace("PersistentKeepalive", "PresharedKey = nope\nPersistentKeepalive")
        assert parse(text).valid is False


class TestEndpoint:
    @pytest.mark.parametrize(
        "bad", ["vpn.example.net", "vpn.example.net:", ":51820", "vpn.example.net:0"]
    )
    def test_an_endpoint_that_is_not_host_and_port(self, bad: str) -> None:
        result = parse(GOOD.replace("vpn.example.net:51820", bad))
        assert result.valid is False
        assert any("host:port" in error for error in result.errors)

    def test_a_bracketed_ipv6_endpoint_is_accepted(self) -> None:
        result = parse(GOOD.replace("vpn.example.net:51820", "[2001:db8::1]:51820"))
        assert result.valid, result.errors
        assert result.config.endpoint_host == "2001:db8::1"

    def test_a_port_past_the_range(self) -> None:
        assert parse(GOOD.replace(":51820", ":70000")).valid is False


class TestAddresses:
    def test_an_address_without_a_prefix_length(self) -> None:
        result = parse(GOOD.replace("10.66.66.2/32", "10.66.66.2/33"))
        assert result.valid is False

    def test_allowed_ips_must_be_networks(self) -> None:
        result = parse(GOOD.replace("0.0.0.0/0", "not-a-network"))
        assert result.valid is False


class TestWarnings:
    def test_a_split_tunnel_is_a_warning_not_an_error(self) -> None:
        # A legitimate choice, but a surprise worth naming: the routing
        # page lists features that would keep using the default route.
        result = parse(GOOD.replace("AllowedIPs = 0.0.0.0/0, ::/0", "AllowedIPs = 10.0.0.0/8"))
        assert result.valid is True
        assert any("0.0.0.0/0" in warning for warning in result.warnings)

    def test_a_bad_dns_entry_does_not_block_saving(self) -> None:
        result = parse(GOOD.replace("DNS = 1.1.1.1", "DNS = not-an-ip"))
        assert result.valid is True
        assert result.warnings


class TestMasking:
    def test_an_exit_ip_shows_its_network_not_its_host(self) -> None:
        # Enough to tell one exit from another; not a location on screen.
        assert mask_ip("203.0.113.42") == "203.0.x.x"

    def test_ipv6_is_masked_too(self) -> None:
        assert mask_ip("2001:db8::1").startswith("2001:db8:")

    def test_nonsense_is_not_shown_as_an_address(self) -> None:
        assert mask_ip("hello") == "unknown"


class TestQualityBands:
    def test_a_clean_tunnel_is_excellent(self) -> None:
        assert quality_band(loss_percent=0.0, jitter_ms=5.0, latency_ms=30.0) == "excellent"

    def test_heavy_loss_is_poor_however_fast_it_is(self) -> None:
        # Worst-of, not an average: a tunnel with perfect latency and 20%
        # loss is unusable, and averaging would hide that.
        assert quality_band(loss_percent=20.0, jitter_ms=1.0, latency_ms=5.0) == "poor"

    def test_each_measure_can_pull_the_band_down_alone(self) -> None:
        assert quality_band(loss_percent=0.0, jitter_ms=0.0, latency_ms=250.0) == "fair"
        assert quality_band(loss_percent=0.0, jitter_ms=70.0, latency_ms=10.0) == "fair"
        assert quality_band(loss_percent=5.0, jitter_ms=0.0, latency_ms=10.0) == "fair"
