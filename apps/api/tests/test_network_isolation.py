"""Exchange traffic stays on the server's own route (SPEC §9, CLAUDE.md rule 3).

Tunnels exist now, so the rule that order and market traffic never use
one has to be held by something stronger than care. These tests read the
source of every module on the exchange path and fail if any of them can
reach the tunnel code or a proxy, and they check the clients those modules
build ignore proxy variables in the environment.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from quanta.exchanges.bitunix import BitunixAdapter
from quanta.exchanges.bitunix_trading import BitunixTradingAdapter

PACKAGE = Path(__file__).resolve().parent.parent / "quanta"

# Everything that talks to an exchange, or decides what is sent to one.
EXCHANGE_PATH = [
    *sorted((PACKAGE / "exchanges").rglob("*.py")),
    PACKAGE / "services" / "execution.py",
    PACKAGE / "services" / "risk.py",
    PACKAGE / "services" / "bot_service.py",
    PACKAGE / "services" / "keyvault.py",
    PACKAGE / "services" / "market_data.py",
    PACKAGE / "services" / "market_store.py",
    PACKAGE / "api" / "routes" / "bots.py",
    PACKAGE / "api" / "routes" / "market.py",
]

FORBIDDEN_IMPORTS = {
    "quanta.services.tunnels",
    "quanta.services.routing",
    "quanta.api.network_runtime",
}


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _proxy_arguments(tree: ast.AST) -> list[str]:
    """Every `proxy=`/`proxies=` passed anywhere, except an explicit None."""
    offending: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg not in {"proxy", "proxies", "mounts"}:
                continue
            if isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
                # Pinning a proxy *off* is the point, not a breach.
                continue
            offending.append(f"line {node.lineno}: {keyword.arg}=")
    return offending


def _module_paths() -> list[Path]:
    return [path for path in EXCHANGE_PATH if path.exists()]


def test_every_listed_module_exists() -> None:
    # A renamed file would otherwise drop out of the check without a sound.
    missing = [str(path.relative_to(PACKAGE)) for path in EXCHANGE_PATH if not path.exists()]
    assert missing == []


@pytest.mark.parametrize("path", _module_paths(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_the_exchange_path_cannot_reach_a_tunnel(path: Path) -> None:
    tree = ast.parse(path.read_text(), filename=str(path))
    assert _imports(tree) & FORBIDDEN_IMPORTS == set()


@pytest.mark.parametrize("path", _module_paths(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_the_exchange_path_never_passes_a_proxy(path: Path) -> None:
    tree = ast.parse(path.read_text(), filename=str(path))
    assert _proxy_arguments(tree) == []


async def test_the_market_data_client_ignores_proxy_variables() -> None:
    # httpx follows HTTPS_PROXY by default; one stray variable on the
    # server would otherwise move exchange traffic off the static IP.
    adapter = BitunixAdapter(rest_url="https://example.invalid", ws_url="wss://example.invalid")
    try:
        assert adapter._client.trust_env is False
    finally:
        await adapter.close()


async def test_the_order_client_ignores_proxy_variables() -> None:
    adapter = BitunixTradingAdapter(rest_url="https://example.invalid")
    try:
        assert adapter._client.trust_env is False
    finally:
        await adapter.close()


def test_the_market_websocket_pins_its_proxy_off() -> None:
    # websockets also reads proxy variables unless told not to.
    source = (PACKAGE / "exchanges" / "bitunix.py").read_text()
    tree = ast.parse(source)
    connects = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect"
    ]
    assert connects, "the websocket connect call moved; update this test"
    for call in connects:
        proxy = [k for k in call.keywords if k.arg == "proxy"]
        assert proxy and isinstance(proxy[0].value, ast.Constant) and proxy[0].value.value is None
