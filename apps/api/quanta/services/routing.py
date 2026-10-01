"""Which network a feature's traffic takes (SPEC §3.6, §9).

A user points each routable feature at an ordered list of their tunnels.
This turns that list into one concrete answer at send time: the proxy of
the first tunnel that is enabled and comes up, or the server's own route
when none does.

**Exchange traffic never reaches this module.** `resolve` refuses the
locked features outright, and the exchange adapters do not import it —
`tests/test_network_isolation.py` fails the build if one ever does. The
refusal here is a second lock, not the first.

**Falling back to the server's own route** is deliberate for the features
that can be routed at all: alert delivery and AI. A tunnel there is about
reachability, so when every tunnel is down, trying the direct path costs
nothing and sometimes works. The fallback is recorded in the result, so
the delivery log says which way a message actually went.

**"Down" means carries nothing, not only "would not start".** The common
failure is a wireproxy that starts, listens, and never completes a
handshake. That is only discovered by sending, so `deliver` watches for
it: a send that failed in the path rather than at the destination marks
the tunnel unreachable for a while and goes out again by the next route.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.models.network import ROUTABLE_FEATURES, UNROUTABLE, FeatureRoute, Tunnel
from quanta.services.notifier import Delivery, Notifier
from quanta.services.tunnels import TunnelError, TunnelManager, open_config

SERVER = "server"
# Mirrors the routes API: a feature lists at most this many tunnels.
MAX_ROUTE_TUNNELS = 4


@dataclass(frozen=True, slots=True)
class Route:
    """The answer for one send."""

    #: `socks5h://…` for a tunnel, None for the server's own route.
    proxy: str | None
    #: What to write in the log: "server" or the tunnel's label.
    via: str = SERVER
    #: Tunnels that were tried and skipped, and why.
    skipped: list[str] = field(default_factory=list)
    #: The tunnel chosen, so a failure through it can be pinned on it.
    tunnel_id: str | None = None

    @property
    def note(self) -> str:
        if not self.skipped:
            return ""
        tail = "sent from the server instead" if self.proxy is None else f"used {self.via}"
        return "; ".join(self.skipped) + f" — {tail}"


async def resolve(
    db: AsyncSession,
    manager: TunnelManager | None,
    user_id: uuid.UUID,
    feature: str,
) -> Route:
    """The route this user's `feature` should take right now."""
    if feature in UNROUTABLE:
        # Defence in depth: the routes API already refuses to store this.
        raise ValueError(f"{feature!r} may not be routed through a tunnel: {UNROUTABLE[feature]}")
    if feature not in ROUTABLE_FEATURES:
        raise ValueError(f"{feature!r} is not a routable feature.")

    stored = await db.execute(
        select(FeatureRoute).where(FeatureRoute.user_id == user_id, FeatureRoute.feature == feature)
    )
    row = stored.scalar_one_or_none()
    tunnel_ids = list(row.tunnel_ids) if row is not None else []
    if not tunnel_ids:
        return Route(proxy=None)

    skipped: list[str] = []
    for raw_id in tunnel_ids:
        tunnel = await db.get(Tunnel, uuid.UUID(str(raw_id)))
        if tunnel is None or tunnel.user_id != user_id:
            continue
        if not tunnel.enabled:
            skipped.append(f"{tunnel.label} is switched off")
            continue
        if manager is None or not manager.available:
            skipped.append(f"{tunnel.label} cannot run here (no wireproxy)")
            continue
        reason = manager.unreachable(str(tunnel.id))
        if reason is not None:
            skipped.append(f"{tunnel.label} carried nothing recently ({reason})")
            continue
        try:
            proxy = await manager.ensure(str(tunnel.id), open_config(tunnel.secret))
        except TunnelError as exc:
            skipped.append(f"{tunnel.label} is down ({exc})")
            continue
        return Route(proxy=proxy, via=tunnel.label, skipped=skipped, tunnel_id=str(tunnel.id))

    return Route(proxy=None, skipped=skipped)


async def deliver(
    db: AsyncSession,
    notifier: Notifier,
    manager: TunnelManager | None,
    user_id: uuid.UUID,
    destinations: list[dict[str, Any]],
    message: str,
    *,
    quiet: bool = False,
    feature: str = "alerts_delivery",
) -> list[Delivery]:
    """Send by the user's route, moving to the next one if a tunnel carries nothing.

    Only the destinations that failed in the path are re-sent; one that
    was refused by the destination itself (a bad chat id, a 404 webhook)
    would be refused by every route, and sending it twice is worse.
    """
    results: dict[int, Delivery] = {}
    pending = list(range(len(destinations)))
    # Each pass either finishes or rules a tunnel out, so this ends; the
    # bound is the routes API's own limit plus the server.
    for _ in range(MAX_ROUTE_TUNNELS + 1):
        route = await resolve(db, manager, user_id, feature)
        sent = await notifier.deliver(
            [destinations[i] for i in pending],
            message,
            quiet=quiet,
            proxy=route.proxy,
            via=route.via,
            route_note=route.note,
        )
        retry: list[int] = []
        for index, delivery in zip(pending, sent, strict=True):
            results[index] = delivery
            if delivery.route_failed and route.tunnel_id is not None:
                retry.append(index)
        if not retry or manager is None or route.tunnel_id is None:
            break
        manager.mark_unreachable(route.tunnel_id, results[retry[0]].note)
        if route.proxy is not None:
            await notifier.forget(route.proxy)
        pending = retry
    return [results[i] for i in range(len(destinations))]
