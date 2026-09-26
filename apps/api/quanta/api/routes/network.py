"""Resources/Network: WireGuard tunnels and routing (SPEC §3.6, §9)."""

from __future__ import annotations

import time
import uuid

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from quanta.api.deps import CurrentUser, DbDep
from quanta.core.config import get_settings
from quanta.models.network import ROUTABLE_FEATURES, UNROUTABLE, FeatureRoute, Tunnel
from quanta.services import wireguard

router = APIRouter(prefix="/network", tags=["network"])

# SPEC §3.6 asks for a test every 30 seconds; this refuses to run one more
# often than that per tunnel, so a page left open cannot become a probe.
MIN_TEST_INTERVAL_SECONDS = 25.0
_last_test: dict[str, float] = {}


def _cipher() -> Fernet:
    """Key derived from the app secret, so a config is unreadable at rest."""
    import base64
    import hashlib

    digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class ValidateRequest(BaseModel):
    config: str = Field(min_length=1, max_length=8000)


class ImportRequest(ValidateRequest):
    label: str = Field(min_length=1, max_length=120)


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


@router.post("/validate")
async def validate_config(payload: ValidateRequest, _user: CurrentUser) -> dict:
    """Check a config without storing it."""
    result = wireguard.parse(payload.config)
    return {
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings,
        "summary": wireguard.summarise(result.config) if result.valid else None,
    }


@router.get("/tunnels")
async def list_tunnels(user: CurrentUser, db: DbDep) -> list[dict]:
    result = await db.execute(
        select(Tunnel).where(Tunnel.user_id == user.id).order_by(Tunnel.priority, Tunnel.created_at)
    )
    return [
        {
            "id": str(tunnel.id),
            "label": tunnel.label,
            "enabled": tunnel.enabled,
            "priority": tunnel.priority,
            "summary": tunnel.summary,
            "last_tested_at": (
                tunnel.last_tested_at.isoformat() if tunnel.last_tested_at else None
            ),
            "last_result": tunnel.last_result,
        }
        for tunnel in result.scalars().all()
    ]


@router.post("/tunnels", status_code=status.HTTP_201_CREATED)
async def import_tunnel(payload: ImportRequest, user: CurrentUser, db: DbDep) -> dict:
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
        secret=_cipher().encrypt(payload.config.encode("utf-8")).decode("ascii"),
        summary=wireguard.summarise(result.config),
        enabled=True,
        priority=0,
        last_result={},
    )
    db.add(tunnel)
    await db.commit()
    await db.refresh(tunnel)
    return {
        "id": str(tunnel.id),
        "label": tunnel.label,
        "enabled": tunnel.enabled,
        "priority": tunnel.priority,
        "summary": tunnel.summary,
        "warnings": result.warnings,
        "last_tested_at": None,
        "last_result": {},
    }


@router.post("/tunnels/{tunnel_id}/test")
async def test_tunnel(tunnel_id: uuid.UUID, user: CurrentUser, db: DbDep) -> dict:
    """Measure the tunnel and band the result.

    The tunnel itself lives in the server's network namespace (SPEC §3.6
    implementation note); this records and bands the measurement. Until
    that namespace exists the result is reported as unavailable rather
    than as a fabricated set of green bars — a quality bar invented from
    nothing is worse than no bar, because it will be believed.
    """
    tunnel = await db.get(Tunnel, tunnel_id)
    if tunnel is None or tunnel.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such tunnel.")

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

    result = {
        "state": "unavailable",
        "detail": (
            "No tunnel namespace is configured on this server, so there is "
            "nothing to measure. Connect one and this will report handshake "
            "age, latency, jitter, loss and the exit IP."
        ),
        "handshake_age_s": None,
        "latency_ms": None,
        "jitter_ms": None,
        "loss_percent": None,
        "exit_ip": None,
        "quality": None,
    }
    tunnel.last_result = result
    from datetime import UTC, datetime

    tunnel.last_tested_at = datetime.now(UTC)
    await db.commit()
    return result


@router.delete("/tunnels/{tunnel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tunnel(
    tunnel_id: uuid.UUID, user: CurrentUser, db: DbDep, response: Response
) -> Response:
    tunnel = await db.get(Tunnel, tunnel_id)
    if tunnel is None or tunnel.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such tunnel.")
    await db.delete(tunnel)
    await db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/routes")
async def list_routes(user: CurrentUser, db: DbDep) -> dict:
    result = await db.execute(select(FeatureRoute).where(FeatureRoute.user_id == user.id))
    stored = {row.feature: [str(t) for t in row.tunnel_ids] for row in result.scalars().all()}
    return {feature: stored.get(feature, []) for feature in ROUTABLE_FEATURES}


@router.put("/routes")
async def set_route(payload: RouteRequest, user: CurrentUser, db: DbDep) -> dict:
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

    for tunnel_id in payload.tunnel_ids:
        tunnel = await db.get(Tunnel, tunnel_id)
        if tunnel is None or tunnel.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such tunnel.")

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


__all__ = ["InvalidToken", "router"]
