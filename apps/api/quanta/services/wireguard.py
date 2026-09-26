"""Parsing and validating WireGuard configuration (SPEC §3.6).

Parsing only. This module reads a config, says whether it is well formed,
and reports what it found — it does not bring a tunnel up. Validation is
worth doing carefully anyway: a config with a truncated key or a missing
port fails at connect time with a message from the kernel that tells the
user nothing, and they have no way to tell a typo from a dead peer.

Private keys are accepted, checked for shape, and never returned. What
comes back is the public key derived from the peer section plus the
endpoint, because that is all the user needs to recognise which tunnel a
row refers to.
"""

from __future__ import annotations

import base64
import ipaddress
import re
from dataclasses import dataclass, field

# WireGuard keys are Curve25519: 32 bytes, base64, always 44 characters
# ending in '='.
KEY_PATTERN = re.compile(r"^[A-Za-z0-9+/]{42}[A-Za-z0-9+/=]{2}$")
SECTION_PATTERN = re.compile(r"^\[(\w+)\]$")
ENTRY_PATTERN = re.compile(r"^([A-Za-z]+)\s*=\s*(.+)$")


@dataclass(slots=True)
class TunnelConfig:
    """A parsed config, with the fields SPEC §3.6 requires."""

    address: list[str] = field(default_factory=list)
    dns: list[str] = field(default_factory=list)
    public_key: str = ""
    endpoint_host: str = ""
    endpoint_port: int = 0
    allowed_ips: list[str] = field(default_factory=list)
    keepalive: int | None = None
    has_private_key: bool = False
    preshared_key: bool = False


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    config: TunnelConfig
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _is_key(value: str) -> bool:
    if not KEY_PATTERN.match(value):
        return False
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
        return False


def _parse_endpoint(value: str) -> tuple[str, int] | None:
    """host:port, including a bracketed IPv6 literal."""
    if value.startswith("["):
        closing = value.find("]")
        if closing == -1 or not value[closing + 1 :].startswith(":"):
            return None
        host, port_text = value[1:closing], value[closing + 2 :]
    else:
        host, separator, port_text = value.rpartition(":")
        if not separator:
            return None

    if not host:
        return None
    try:
        port = int(port_text)
    except ValueError:
        return None
    if not 1 <= port <= 65_535:
        return None
    return host, port


def parse(text: str) -> ValidationResult:
    """Read a config and say exactly what is wrong with it, if anything."""
    sections: dict[str, dict[str, str]] = {}
    current: str | None = None

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        section = SECTION_PATTERN.match(line)
        if section:
            current = section.group(1).lower()
            sections.setdefault(current, {})
            continue
        entry = ENTRY_PATTERN.match(line)
        if entry and current is not None:
            # Last wins, which is what wg-quick does.
            sections[current][entry.group(1).lower()] = entry.group(2).strip()

    errors: list[str] = []
    warnings: list[str] = []
    config = TunnelConfig()

    interface = sections.get("interface")
    peer = sections.get("peer")
    if interface is None:
        errors.append("No [Interface] section.")
    if peer is None:
        errors.append("No [Peer] section.")
    if interface is None or peer is None:
        return ValidationResult(False, config, errors, warnings)

    private_key = interface.get("privatekey", "")
    if not private_key:
        errors.append("[Interface] has no PrivateKey.")
    elif not _is_key(private_key):
        errors.append("The PrivateKey is not 32 bytes of base64.")
    else:
        config.has_private_key = True

    address = interface.get("address", "")
    if not address:
        errors.append("[Interface] has no Address.")
    else:
        for part in (piece.strip() for piece in address.split(",")):
            try:
                ipaddress.ip_interface(part)
            except ValueError:
                errors.append(f"Address {part!r} is not an IP with a prefix length.")
            else:
                config.address.append(part)

    dns = interface.get("dns", "")
    for part in (piece.strip() for piece in dns.split(",") if piece.strip()):
        try:
            ipaddress.ip_address(part)
        except ValueError:
            warnings.append(f"DNS {part!r} is not an IP address.")
        else:
            config.dns.append(part)

    public_key = peer.get("publickey", "")
    if not public_key:
        errors.append("[Peer] has no PublicKey.")
    elif not _is_key(public_key):
        errors.append("The peer PublicKey is not 32 bytes of base64.")
    else:
        config.public_key = public_key

    preshared = peer.get("presharedkey", "")
    if preshared:
        if _is_key(preshared):
            config.preshared_key = True
        else:
            errors.append("The PresharedKey is not 32 bytes of base64.")

    endpoint = peer.get("endpoint", "")
    if not endpoint:
        errors.append("[Peer] has no Endpoint.")
    else:
        parsed = _parse_endpoint(endpoint)
        if parsed is None:
            errors.append(f"Endpoint {endpoint!r} is not host:port.")
        else:
            config.endpoint_host, config.endpoint_port = parsed

    allowed = peer.get("allowedips", "")
    if not allowed:
        errors.append("[Peer] has no AllowedIPs.")
    else:
        for part in (piece.strip() for piece in allowed.split(",")):
            try:
                ipaddress.ip_network(part, strict=False)
            except ValueError:
                errors.append(f"AllowedIPs {part!r} is not a network.")
            else:
                config.allowed_ips.append(part)

    keepalive = peer.get("persistentkeepalive", "")
    if keepalive:
        try:
            config.keepalive = int(keepalive)
        except ValueError:
            warnings.append("PersistentKeepalive is not a number.")
        else:
            if not 0 <= config.keepalive <= 65_535:
                warnings.append("PersistentKeepalive is outside 0 to 65535.")

    if config.allowed_ips and "0.0.0.0/0" not in config.allowed_ips:
        # Not an error — a split tunnel is a legitimate choice — but a
        # surprise worth naming, since the routing page lists features
        # that would silently keep using the default route.
        warnings.append(
            "AllowedIPs does not include 0.0.0.0/0, so only the listed "
            "networks will go through this tunnel."
        )

    return ValidationResult(not errors, config, errors, warnings)


def summarise(config: TunnelConfig) -> dict[str, object]:
    """What is safe to show about a stored tunnel."""
    return {
        "endpoint": (
            f"{config.endpoint_host}:{config.endpoint_port}" if config.endpoint_host else ""
        ),
        "public_key": config.public_key,
        "address": config.address,
        "dns": config.dns,
        "allowed_ips": config.allowed_ips,
        "keepalive": config.keepalive,
        "has_preshared_key": config.preshared_key,
    }


def mask_ip(address: str) -> str:
    """An exit IP with its host part hidden.

    Shown so the user can tell one exit from another; masked because a
    full address is a location, and it does not need to be on screen to
    answer "is this the tunnel I think it is".
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return "unknown"
    if parsed.version == 4:
        octets = address.split(".")
        return f"{octets[0]}.{octets[1]}.x.x"
    head = address.split(":")[:2]
    return ":".join(head) + ":…"


def quality_band(*, loss_percent: float, jitter_ms: float, latency_ms: float) -> str:
    """Excellent / Good / Fair / Poor, worst-of the three (SPEC §3.6).

    Worst-of rather than an average: a tunnel with perfect latency and 20%
    loss is not "good on balance", it is unusable, and averaging would
    hide that behind two healthy numbers.
    """
    if loss_percent >= 10 or latency_ms >= 400 or jitter_ms >= 120:
        return "poor"
    if loss_percent >= 3 or latency_ms >= 200 or jitter_ms >= 60:
        return "fair"
    if loss_percent >= 1 or latency_ms >= 100 or jitter_ms >= 25:
        return "good"
    return "excellent"
