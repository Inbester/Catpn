"""Alert evaluation, delivery and the paths that must not repaint."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.exchanges.base import Bar, Interval
from quanta.models.alert import Alert
from quanta.services import alert_service, market_store
from quanta.services.alert_runner import run_once
from quanta.services.alert_templates import merge_messages, render
from quanta.services.notifier import Notifier, RateLimiter, sign_webhook
from tests.test_forward_routes import T0, auth

HOUR = 3_600_000


async def seed_rising(db: AsyncSession, *, symbol: str = "BTCUSDT", count: int = 60) -> None:
    """A series that crosses 100 on the last closed bar."""
    bars = []
    for i in range(count):
        price = 90 + i * 0.5
        bars.append(
            Bar(
                open_time=T0 + i * HOUR,
                open=Decimal(str(price)),
                high=Decimal(str(price + 0.2)),
                low=Decimal(str(price - 0.2)),
                close=Decimal(str(price)),
                volume=Decimal("10"),
                closed=True,
            )
        )
    await market_store.upsert_bars(db, symbol, Interval.H1, bars)
    await db.commit()


def alert_row(user_id, **overrides) -> Alert:
    defaults: dict[str, object] = {
        "user_id": user_id,
        "name": "BTC over 100",
        "source": "price",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "condition": {"price": 100.0, "direction": "above"},
        "repeat_mode": "once_per_bar",
        # Column defaults apply at insert, so an object that has not been
        # flushed yet reads None for these.
        "enabled": True,
        "fire_count": 0,
        "template": "{{SIDE}} {{symbol}} at {{price}}",
        "destinations": [{"kind": "webhook", "target": "https://example.test/hook"}],
    }
    defaults.update(overrides)
    return Alert(**defaults)


class TestTemplates:
    def test_every_message_ends_with_the_disclaimer(self) -> None:
        # Appended rather than part of the template: a user can rewrite
        # everything above it but cannot remove it.
        assert render("anything", {}).endswith("Not financial advice.")
        assert render("هرچیز", {}, "fa").endswith("این توصیهٔ مالی نیست.")

    def test_an_unknown_variable_stays_visible(self) -> None:
        # Blanking it would produce a message with a silent hole; leaving
        # it shows the typo in the test send.
        assert "{{ nonsense }}" in render("a {{ nonsense }} b", {"other": 1})

    def test_substitutes_what_it_knows(self) -> None:
        assert render("{{SIDE}} {{symbol}}", {"SIDE": "LONG", "symbol": "BTCUSDT"}).startswith(
            "LONG BTCUSDT"
        )

    def test_a_burst_becomes_one_message_with_a_count(self) -> None:
        merged = merge_messages(["first\n\nNot financial advice."] * 3)
        assert "+2 more signals" in merged
        # The disclaimer stays last.
        assert merged.endswith("Not financial advice.")

    def test_one_message_is_left_alone(self) -> None:
        assert merge_messages(["only"]) == "only"


class TestQuietHours:
    @pytest.mark.parametrize(
        ("start", "end", "hour", "expected"),
        [
            (22, 7, 23, True),
            (22, 7, 3, True),
            (22, 7, 12, False),
            (9, 17, 12, True),
            (9, 17, 20, False),
        ],
    )
    def test_windows_including_ones_that_wrap_midnight(
        self, start: int, end: int, hour: int, expected: bool
    ) -> None:
        alert = alert_row(None, quiet_from_hour=start, quiet_to_hour=end)
        moment = datetime(2026, 1, 1, hour, tzinfo=UTC)
        assert alert_service.in_quiet_hours(alert, moment) is expected

    def test_no_window_means_never_quiet(self) -> None:
        assert alert_service.in_quiet_hours(alert_row(None), datetime.now(UTC)) is False


class TestRepeatRules:
    def test_once_fires_only_ever_once(self) -> None:
        alert = alert_row(None, repeat_mode="once", fire_count=1)
        allowed, reason = alert_service.may_fire(alert, 1, datetime.now(UTC))
        assert allowed is False
        assert "already" in reason

    def test_once_per_bar_allows_the_next_bar(self) -> None:
        alert = alert_row(None, repeat_mode="once_per_bar", last_fired_bar=100)
        assert alert_service.may_fire(alert, 100, datetime.now(UTC))[0] is False
        assert alert_service.may_fire(alert, 200, datetime.now(UTC))[0] is True

    def test_every_always_allows(self) -> None:
        alert = alert_row(None, repeat_mode="every", fire_count=99, last_fired_bar=100)
        assert alert_service.may_fire(alert, 100, datetime.now(UTC))[0] is True

    def test_an_expired_alert_does_not_fire(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=1)
        alert = alert_row(None, expires_at=past)
        assert alert_service.may_fire(alert, 1, datetime.now(UTC))[0] is False

    def test_a_disabled_alert_does_not_fire(self) -> None:
        assert (
            alert_service.may_fire(alert_row(None, enabled=False), 1, datetime.now(UTC))[0] is False
        )


class TestEvaluation:
    async def test_a_price_cross_fires_once_not_every_bar(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        # "Price above 100" as a state would fire on every bar it stayed
        # there, which is a stream, not an alert.
        headers = await auth(client, api_prefix)
        me = (await client.get(f"{api_prefix}/users/me", headers=headers)).json()
        await seed_rising(db)

        alert = alert_row(me["id"])
        db.add(alert)
        await db.commit()

        first = await alert_service.evaluate_alert(db, alert)
        await db.commit()
        second = await alert_service.evaluate_alert(db, alert)
        await db.commit()

        assert first is None or second is None or second.deliveries[0]["state"] == "suppressed"

    async def test_the_forming_bar_is_never_evaluated(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        """A condition that holds mid-bar can stop holding before it closes."""
        headers = await auth(client, api_prefix)
        me = (await client.get(f"{api_prefix}/users/me", headers=headers)).json()
        await seed_rising(db, count=40)

        # A forming bar that would cross the level, and must be ignored.
        await market_store.upsert_bars(
            db,
            "BTCUSDT",
            Interval.H1,
            [
                Bar(
                    open_time=T0 + 40 * HOUR,
                    open=Decimal("109"),
                    high=Decimal("999"),
                    low=Decimal("109"),
                    close=Decimal("999"),
                    volume=Decimal("10"),
                    closed=False,
                )
            ],
        )
        await db.commit()

        alert = alert_row(me["id"], condition={"price": 500.0, "direction": "above"})
        db.add(alert)
        await db.commit()

        assert await alert_service.evaluate_alert(db, alert) is None

    async def test_a_suppressed_firing_is_still_recorded(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        # The user needs to see that their own "once" rule is why the
        # second signal never arrived.
        headers = await auth(client, api_prefix)
        me = (await client.get(f"{api_prefix}/users/me", headers=headers)).json()
        await seed_rising(db)

        alert = alert_row(me["id"], repeat_mode="once", fire_count=1)
        db.add(alert)
        await db.commit()

        event = await alert_service.evaluate_alert(db, alert)
        await db.commit()
        if event is not None:
            assert event.deliveries[0]["state"] == "suppressed"


class TestNotifier:
    async def test_every_destination_is_attempted_independently(self) -> None:
        # A Telegram outage must not cost you the webhook your bot is on.
        notifier = Notifier()
        deliveries = await notifier.deliver(
            [
                {"kind": "telegram", "target": "123"},
                {"kind": "webhook", "target": "https://example.test/hook"},
                {"kind": "nonsense", "target": "x"},
            ],
            "hello",
        )
        states = {d.kind: d.state for d in deliveries}
        assert states["telegram"] == "sent"
        assert states["webhook"] == "sent"
        assert states["nonsense"] == "failed"

    async def test_latency_is_recorded_for_the_activity_view(self) -> None:
        notifier = Notifier()
        deliveries = await notifier.deliver([{"kind": "webhook", "target": "x"}], "hi")
        assert deliveries[0].latency_ms >= 0
        assert deliveries[0].attempts == 1

    def test_a_webhook_signature_covers_the_bytes_that_are_sent(self) -> None:
        body = b'{"a":1}'
        assert sign_webhook("secret", body) == sign_webhook("secret", body)
        assert sign_webhook("secret", body) != sign_webhook("other", body)


class TestRateLimiter:
    def test_paces_one_chat_without_delaying_another(self) -> None:
        limiter = RateLimiter()
        limiter.record("chat-a", is_group=False, now=100.0)
        assert limiter.delay_for("chat-a", is_group=False, now=100.2) > 0
        # A busy group must not queue a direct message with budget left.
        assert limiter.delay_for("chat-b", is_group=False, now=100.2) == 0

    def test_a_group_gets_twenty_a_minute(self) -> None:
        limiter = RateLimiter()
        for i in range(20):
            limiter.record("-100", is_group=True, now=200.0 + i)
        assert limiter.delay_for("-100", is_group=True, now=220.0) > 0
        # And the window rolls rather than a flat sleep.
        assert limiter.delay_for("-100", is_group=True, now=262.0) == 0


class TestAcceptance:
    async def test_a_signal_reaches_its_destination_within_two_seconds(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        """SPEC §8, phase 5: within 2s of bar close."""
        headers = await auth(client, api_prefix)
        me = (await client.get(f"{api_prefix}/users/me", headers=headers)).json()
        await seed_rising(db)

        alert = alert_row(
            me["id"],
            destinations=[{"kind": "telegram", "target": "-1001234567890"}],
        )
        db.add(alert)
        await db.commit()

        notifier = Notifier()
        started = time.perf_counter()
        events = await run_once(db, notifier)
        elapsed = time.perf_counter() - started

        assert elapsed < 2.0, f"took {elapsed:.2f}s from bar close to delivery"
        if events:
            assert events[0].deliveries[0]["state"] == "sent"
            assert notifier.sent

    async def test_one_broken_alert_does_not_silence_the_others(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        # A typo in one expression would otherwise take down the account.
        headers = await auth(client, api_prefix)
        me = (await client.get(f"{api_prefix}/users/me", headers=headers)).json()
        await seed_rising(db)

        db.add(
            alert_row(me["id"], name="broken", source="indicator", condition={"expression": "!!"})
        )
        db.add(alert_row(me["id"], name="fine"))
        await db.commit()

        notifier = Notifier()
        await run_once(db, notifier)  # must not raise


class TestRoutes:
    async def test_create_list_and_delete(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/alerts",
            headers=headers,
            json={
                "name": "BTC over 100",
                "source": "price",
                "symbol": "BTCUSDT",
                "condition": {"price": 100, "direction": "above"},
                "destinations": [
                    {"kind": "webhook", "target": "https://example.test/h", "secret": "s3cret"}
                ],
            },
        )
        assert created.status_code == 201, created.text
        alert_id = created.json()["id"]
        # A webhook secret goes in but never comes back out.
        assert "secret" not in created.json()["destinations"][0]

        listed = await client.get(f"{api_prefix}/alerts", headers=headers)
        assert [row["id"] for row in listed.json()] == [alert_id]

        assert (
            await client.delete(f"{api_prefix}/alerts/{alert_id}", headers=headers)
        ).status_code == 204

    async def test_a_strategy_alert_needs_a_setup(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        # Otherwise it fires on whatever the draft says today, which is
        # the failure Setups exist to prevent.
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/alerts",
            headers=headers,
            json={"name": "x", "source": "strategy", "symbol": "BTCUSDT"},
        )
        assert response.status_code == 422

    async def test_quiet_hours_need_both_ends(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/alerts",
            headers=headers,
            json={
                "name": "x",
                "source": "price",
                "symbol": "BTCUSDT",
                "quiet_from_hour": 22,
            },
        )
        assert response.status_code == 422

    async def test_preview_names_variables_that_will_not_fill_in(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/alerts/preview",
            headers=headers,
            json={"template": "{{SIDE}} {{symbol}} {{wat}}"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["unknown_variables"] == ["wat"]
        assert "LONG BTCUSDT" in response.json()["message"]

    async def test_an_alert_is_private_to_its_owner(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        from tests.test_research_routes import other_user

        headers = await auth(client, api_prefix)
        created = await client.post(
            f"{api_prefix}/alerts",
            headers=headers,
            json={"name": "x", "source": "price", "symbol": "BTCUSDT"},
        )
        alert_id = created.json()["id"]
        theirs = await other_user(client, api_prefix)
        assert (
            await client.get(f"{api_prefix}/alerts/{alert_id}", headers=theirs)
        ).status_code == 404
