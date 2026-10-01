"""Process-wide handles to the tunnel manager and the live notifier.

Both own long-lived state — running wireproxy processes, pooled HTTP
clients — so there is exactly one of each per process, created at boot and
closed at shutdown. Routes reach them through here, the same way they reach
the market-data service.

Unset in tests that do not start the app's lifespan; callers then fall
back to a recording notifier and no tunnels, which is the honest behaviour
for an environment with neither.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quanta.services.notifier import Notifier
    from quanta.services.tunnels import TunnelManager

_tunnels: TunnelManager | None = None
_notifier: Notifier | None = None


def set_runtime(tunnels: TunnelManager | None, notifier: Notifier | None) -> None:
    global _tunnels, _notifier
    _tunnels = tunnels
    _notifier = notifier


def get_tunnels() -> TunnelManager | None:
    return _tunnels


def get_notifier() -> Notifier | None:
    return _notifier
