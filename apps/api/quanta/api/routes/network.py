"""Resources/Network: WireGuard tunnels and routing (SPEC §3.6, §9).

The tunnels are real: each runs as a wireproxy process on the server (see
services/tunnels.py), the Test button sends real requests through it, and
alert delivery uses whichever one the user put first. What this module
never does is hand a tunnel to exchange traffic — the routes endpoint
refuses the locked features, and services/routing.py refuses them again.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from quanta.api.deps import CurrentUser, DbDep
from quanta.api.network_runtime import get_notifier, get_tunnels
from quanta.core.config import get_settings
from quanta.models.network import ROUTABLE_FEATURES, UNROUTABLE, FeatureRoute, Tunnel
from quanta.services import tunnels as tunnel_service
from quanta.services import wireguard

router = APIRouter(prefix="/network", tags=["network"])

# SPEC §3.6 asks for a test every 30 seconds; this refuses to run one more
# often than that per tunnel, so a page left open cannot become a probe.
MIN_TEST_INTERVAL_SECONDS = 25.0
_last_test: dict[str, float] = {}


def _engine() -> dict[str, Any]:
    manager = get_tunnels()
    if manager is None:
        return {
            "available": False,
            "amnezia": False,
            "detail": "The tunnel manager is not running in this process.",
        }
    return manager.engine()


def _state(tunnel: Tunnel) -> tuple[str, str | None]:
    """What the tunnel is doing right now, and the last reason it failed."""
    manager = get_tunnels()
    if manager is None:
        return "unavailable", None
    key = str(tunnel.id)
    if not tunnel.enabled:
        return "off", None
    return manager.state(key), manager.last_error(key)


def _row(tunnel: Tunnel, *, warnings: list[str] | None = None) -> dict[str, Any]:
    state, error = _state(tunnel)
    row: dict[str, Any] = {
        "id": str(tunnel.id),
        "label": tunnel.label,
        "enabled": tunnel.enabled,
        "priority": tunnel.priority,
        "summary": tunnel.summary,
        "state": state,
        "last_error": error,
        "last_tested_at": (tunnel.last_tested_at.isoformat() if tunnel.last_tested_at else None),
        "last_result": tunnel.last_result,
    }
    if warnings is not None:
        row["warnings"] = warnings
    return row


async def _owned(db: DbDep, user_id: uuid.UUID, tunnel_id: uuid.UUID) -> Tunnel:
    tunnel = await db.get(Tunnel, tunnel_id)
    if tunnel is None or tunnel.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such tunnel.")
    return tunnel


async def _shut(tunnel_id: str) -> None:
    """Stop a tunnel and drop the pooled client that pointed at it."""
    manager = get_tunnels()
    if manager is None:
        return
    proxy = manager.proxy_for(tunnel_id)
    await manager.stop(tunnel_id)
    notifier = get_notifier()
    if proxy is not None and notifier is not None:
        await notifier.forget(proxy)


class ValidateRequest(BaseModel):
    config: str = Field(min_length=1, max_length=8000)


class ImportRequest(ValidateRequest):
    label: str = Field(min_length=1, max_length=120)


class TunnelUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=100)


class RouteRequest(BaseModel):
    feature: str = Field(max_length=32)
    tunnel_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)


@router.get("/features")
async def list_features(_user: CurrentUser) -> dict:
    """What may be routed, and what may not, with the reason for each.

    The locked set is returned rather than omitted: a control that is
    silently absent looks like a missing feature, and the reason is the
    part the user actually needs.
    """
    return {"routable": list(ROUTABLE_FEATURES), "locked": UNROUTABLE}


@router.get("/engine")
async def engine(_user: CurrentUser) -> dict[str, Any]:
    """Whether this server can run tunnels at all, and AmneziaWG ones."""
    return _engine()


@router.post("/validate")
async def validate_config(payload: ValidateRequest, _user: CurrentUser) -> dict:
    """Check a config without storing it."""
    result = wireguard.parse(payload.config)
    return {
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings + _runtime_warnings(payload.config),
        "summary": wireguard.summarise(result.config) if result.valid else None,
    }


def _runtime_warnings(config: str) -> list[str]:
    """What the parser cannot know: how this server will actually run it."""
    warnings: list[str] = []
    if tunnel_service.is_amnezia(config) and not _engine()["amnezia"]:
        warnings.append(
            "This is an AmneziaWG config. This server runs plain WireGuard, which would accept "
            "it and then never connect, so it will not be started until the AmneziaWG build "
            "is installed."
        )
    if not tunnel_service.has_dns(config):
        warnings.append(
            f"No DNS server is set, so {tunnel_service.DEFAULT_DNS} will be used through the "
            "tunnel."
        )
    return warnings


@router.get("/tunnels")
async def list_tunnels(user: CurrentUser, db: DbDep) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Tunnel).where(Tunnel.user_id == user.id).order_by(Tunnel.priority, Tunnel.created_at)
    )
    return [_row(tunnel) for tunnel in result.scalars().all()]


@router.post("/tunnels", status_code=status.HTTP_201_CREATED)
async def import_tunnel(payload: ImportRequest, user: CurrentUser, db: DbDep) -> dict[str, Any]:
    """Validate, then store with the private key encrypted."""
    result = wireguard.parse(payload.config)
    if not result.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="; ".join(result.errors),
        )

    tunnel = Tunnel(
        user_id=user.id,
        label=payload.label,
        # Encrypted at rest and never returned (SPEC §3.6).
        secret=tunnel_service.seal_config(payload.config),
        summary=wireguard.summarise(result.config),
        enabled=True,
        priority=0,
        last_result={},
    )
    db.add(tunnel)
    await db.commit()
    await db.refresh(tunnel)
    return _row(tunnel, warnings=result.warnings + _runtime_warnings(payload.config))


@router.patch("/tunnels/{tunnel_id}")
async def update_tunnel(
    tunnel_id: uuid.UUID, payload: TunnelUpdate, user: CurrentUser, db: DbDep
) -> dict[str, Any]:
    """Rename, reorder, or switch a tunnel on or off.

    Switching off stops the process at once. A route that names the tunnel
    keeps it in its list and skips it, so turning it back on restores the
    route the user built rather than making them build it again.
    """
    tunnel = await _owned(db, user.id, tunnel_id)
    if payload.label is not None:
        tunnel.label = payload.label
    if payload.priority is not None:
        tunnel.priority = payload.priority
    if payload.enabled is not None:
        tunnel.enabled = payload.enabled
    await db.commit()
    await db.refresh(tunnel)
    if not tunnel.enabled:
        await _shut(str(tunnel.id))
    return _row(tunnel)


@router.post("/tunnels/{tunnel_id}/test")
async def test_tunnel(tunnel_id: uuid.UUID, user: CurrentUser, db: DbDep) -> dict[str, Any]:
    """Bring the tunnel up and send real requests through it.

    Reports the exit IP, latency, jitter and loss that came back. When the
    server cannot run tunnels the result says so: a quality bar invented
    from nothing is worse than no bar, because it will be believed.
    """
    tunnel = await _owned(db, user.id, tunnel_id)

    key = str(tunnel.id)
    now = time.monotonic()
    previous = _last_test.get(key)
    if previous is not None and now - previous < MIN_TEST_INTERVAL_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Tested {now - previous:.0f}s ago; tests run at most every "
            f"{MIN_TEST_INTERVAL_SECONDS:.0f}s.",
        )
    _last_test[key] = now

    result = await _measure(tunnel)
    tunnel.last_result = result
    tunnel.last_tested_at = datetime.now(UTC)
    await db.commit()
    return result


def _empty(state: str, detail: str) -> dict[str, Any]:
    return {
        "state": state,
        "detail": detail,
        "handshake_age_s": None,
        "latency_ms": None,
        "jitter_ms": None,
        "loss_percent": None,
        "exit_ip": None,
        "quality": None,
    }


async def _measure(tunnel: Tunnel) -> dict[str, Any]:
    manager = get_tunnels()
    if manager is None or not manager.available:
        return _empty("unavailable", _engine()["detail"])
    if not tunnel.enabled:
        return _empty("off", "This tunnel is switched off. Turn it on to test it.")
    try:
        proxy = await manager.ensure(str(tunnel.id), tunnel_service.open_config(tunnel.secret))
    except tunnel_service.TunnelError as exc:
        return _empty("failed", str(exc))
    result = await tunnel_service.probe(proxy, url=get_settings().tunnel_probe_url)
    # A test is the user asking "does it work now?"; the answer also tells
    # alert delivery whether to use it.
    if result["state"] == "ok":
        manager.mark_reachable(str(tunnel.id))
    else:
        manager.mark_unreachable(str(tunnel.id), result["detail"])
    return result


@router.delete("/tunnels/{tunnel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tunnel(
    tunnel_id: uuid.UUID, user: CurrentUser, db: DbDep, response: Response
) -> Response:
    tunnel = await _owned(db, user.id, tunnel_id)
    await _shut(str(tunnel.id))
    # Take it out of every route too, so the page never lists a fallback
    # that no longer exists.
    routes = await db.execute(select(FeatureRoute).where(FeatureRoute.user_id == user.id))
    for route in routes.scalars().all():
        if str(tunnel.id) in route.tunnel_ids:
            route.tunnel_ids = [t for t in route.tunnel_ids if t != str(tunnel.id)]
    await db.delete(tunnel)
    await db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/routes")
async def list_routes(user: CurrentUser, db: DbDep) -> dict[str, list[str]]:
    result = await db.execute(select(FeatureRoute).where(FeatureRoute.user_id == user.id))
    stored = {row.feature: [str(t) for t in row.tunnel_ids] for row in result.scalars().all()}
    return {feature: stored.get(feature, []) for feature in ROUTABLE_FEATURES}


@router.put("/routes")
async def set_route(payload: RouteRequest, user: CurrentUser, db: DbDep) -> dict[str, list[str]]:
    """Point a feature at an ordered list of tunnels.

    A locked feature is refused with its reason rather than quietly
    ignored: someone trying to route market data needs to be told that the
    product will not do it, and why.
    """
    if payload.feature in UNROUTABLE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=UNROUTABLE[payload.feature],
        )
    if payload.feature not in ROUTABLE_FEATURES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{payload.feature!r} is not a routable feature.",
        )

    if len(set(payload.tunnel_ids)) != len(payload.tunnel_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A tunnel can appear only once in a route.",
        )
    for tunnel_id in payload.tunnel_ids:
        await _owned(db, user.id, tunnel_id)

    result = await db.execute(
        select(FeatureRoute).where(
            FeatureRoute.user_id == user.id, FeatureRoute.feature == payload.feature
        )
    )
    route = result.scalar_one_or_none()
    if route is None:
        route = FeatureRoute(user_id=user.id, feature=payload.feature, tunnel_ids=[])
        db.add(route)
    route.tunnel_ids = [str(t) for t in payload.tunnel_ids]
    await db.commit()
    return {payload.feature: route.tunnel_ids}
