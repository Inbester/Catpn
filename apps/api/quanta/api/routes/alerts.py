"""Alerts, their activity and the channels they send to (SPEC §3.4, §7)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from quanta.api.deps import CurrentUser, DbDep
from quanta.models.alert import Alert, AlertEvent, Channel
from quanta.models.setup import Setup
from quanta.schemas.alert import (
    AlertEventResponse,
    AlertPayload,
    AlertResponse,
    ChannelPayload,
    ChannelResponse,
    PreviewRequest,
    PreviewResponse,
    TestSendRequest,
)
from quanta.services import alert_service
from quanta.services.alert_templates import VARIABLE_PATTERN, build_context, render
from quanta.services.notifier import Notifier

router = APIRouter(prefix="/alerts", tags=["alerts"])
channels_router = APIRouter(prefix="/channels", tags=["channels"])


async def _owned(db: DbDep, user: CurrentUser, alert_id: uuid.UUID) -> Alert:
    alert = await db.get(Alert, alert_id)
    if alert is None or alert.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such alert.")
    return alert


def _to_response(alert: Alert) -> AlertResponse:
    response = AlertResponse.model_validate(alert)
    # Webhook secrets go in but never come back out.
    response.destinations = [
        {key: value for key, value in destination.items() if key != "secret"}
        for destination in alert.destinations
    ]
    return response


@router.get("", response_model=list[AlertResponse])
async def list_alerts(
    user: CurrentUser, db: DbDep, enabled_only: bool = Query(default=False)
) -> list[AlertResponse]:
    statement = select(Alert).where(Alert.user_id == user.id)
    if enabled_only:
        statement = statement.where(Alert.enabled.is_(True))
    result = await db.execute(statement.order_by(Alert.created_at.desc()))
    return [_to_response(alert) for alert in result.scalars().all()]


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(payload: AlertPayload, user: CurrentUser, db: DbDep) -> AlertResponse:
    if payload.setup_id is not None:
        setup = await db.get(Setup, payload.setup_id)
        if setup is None or setup.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such setup.")

    alert = Alert(
        user_id=user.id,
        **payload.model_dump(exclude={"destinations"}),
        destinations=[d.model_dump() for d in payload.destinations],
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return _to_response(alert)


@router.get("/events", response_model=list[AlertEventResponse])
async def list_events(user: CurrentUser, db: DbDep) -> list[AlertEventResponse]:
    """The activity feed: every firing with per-destination status."""
    events = await alert_service.recent_events(db, user.id)
    return [AlertEventResponse.model_validate(event) for event in events]


@router.post("/preview", response_model=PreviewResponse)
async def preview(payload: PreviewRequest, _user: CurrentUser) -> PreviewResponse:
    """Render a template without sending it, naming what will not fill in."""
    context = build_context(
        side="long",
        symbol="BTCUSDT",
        interval="1h",
        price=68_000.0,
        strategy="BTC 1h Trend",
        version="abc123def456",
        stop_loss=66_640.0,
        take_profit=70_720.0,
        size="10%",
        leverage="5x",
        time_tehran="1404-07-04 18:30",
        **payload.context,
    )
    message = render(payload.template, context, payload.locale)
    unknown = sorted(
        {name for name in VARIABLE_PATTERN.findall(payload.template) if name not in context}
    )
    return PreviewResponse(message=message, unknown_variables=unknown)


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: uuid.UUID, user: CurrentUser, db: DbDep) -> AlertResponse:
    return _to_response(await _owned(db, user, alert_id))


@router.put("/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: uuid.UUID, payload: AlertPayload, user: CurrentUser, db: DbDep
) -> AlertResponse:
    alert = await _owned(db, user, alert_id)
    for field, value in payload.model_dump(exclude={"destinations"}).items():
        setattr(alert, field, value)
    alert.destinations = [d.model_dump() for d in payload.destinations]
    await db.commit()
    await db.refresh(alert)
    return _to_response(alert)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: uuid.UUID, user: CurrentUser, db: DbDep, response: Response
) -> Response:
    alert = await _owned(db, user, alert_id)
    await db.delete(alert)
    await db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/{alert_id}/test", response_model=AlertEventResponse)
async def test_send(
    alert_id: uuid.UUID, payload: TestSendRequest, user: CurrentUser, db: DbDep
) -> AlertEventResponse:
    """Send now, to this alert's own destinations.

    Recorded in the activity feed like any other firing: a test that does
    not appear where real sends appear tests a different path.
    """
    alert = await _owned(db, user, alert_id)
    context = build_context(
        side="long",
        symbol=alert.symbol,
        interval=alert.interval,
        price=0.0,
        strategy=alert.name,
        time_tehran="",
    )
    message = payload.message or render(alert.template, context, alert.locale)

    notifier = Notifier()
    deliveries = await notifier.deliver(alert.destinations, message, quiet=False)

    event = AlertEvent(
        alert_id=alert.id,
        user_id=user.id,
        bar_time=0,
        price="0",
        message=message,
        context={"test": True},
        deliveries=[d.to_dict() for d in deliveries],
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return AlertEventResponse.model_validate(event)


@channels_router.get("", response_model=list[ChannelResponse])
async def list_channels(user: CurrentUser, db: DbDep) -> list[ChannelResponse]:
    result = await db.execute(
        select(Channel).where(Channel.user_id == user.id).order_by(Channel.created_at.desc())
    )
    return [ChannelResponse.model_validate(row) for row in result.scalars().all()]


@channels_router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_channel(payload: ChannelPayload, user: CurrentUser, db: DbDep) -> ChannelResponse:
    channel = Channel(
        user_id=user.id,
        kind=payload.kind,
        label=payload.label,
        target=payload.target,
        secrets=payload.secrets,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return ChannelResponse.model_validate(channel)


@channels_router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: uuid.UUID, user: CurrentUser, db: DbDep, response: Response
) -> Response:
    channel = await db.get(Channel, channel_id)
    if channel is None or channel.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such channel.")
    await db.delete(channel)
    await db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
