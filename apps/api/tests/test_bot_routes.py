"""Exchange keys and bots over HTTP.

The things worth asserting here are the refusals: a secret that comes
back, a key deleted out from under a running bot, a bot armed without 2FA
or without passing paper trading, a kill switch reached by accident. Each
one is a way for the product to lose someone money.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.api.routes import bots as bot_routes
from quanta.core.config import get_settings
from quanta.exchanges.sim.trading import (
    SIM_SERVER_IP,
    SimAccount,
    SimulatedTradingAdapter,
    default_permissions,
)
from quanta.exchanges.trading import KeyPermissions, OrderRequest, OrderSide, OrderType
from quanta.models.bot import Bot, ExchangeKey
from quanta.models.setup import Setup
from quanta.models.user import User
from quanta.services import bot_service
from quanta.services.keyvault import KeyVault
from tests.test_auth_routes import login, register
from tests.test_forward_routes import make_strategy

SYMBOL = "BTCUSDT"
API_KEY = "sim-api-key-0001"
API_SECRET = "sim-secret"

LIMITS = {
    "max_position_notional": "10000",
    "max_daily_loss": "500",
    "max_drawdown_percent": "20",
    "max_leverage": 10,
    "max_orders_per_minute": 6,
}


@pytest.fixture(autouse=True)
def venue() -> Iterator[SimulatedTradingAdapter]:
    """Point the routes at the simulator, and put the static IP in settings."""
    adapter = SimulatedTradingAdapter(prices={SYMBOL: Decimal(100)})
    adapter.add_account(API_KEY)
    bot_routes.set_trading_adapter(adapter)

    settings = get_settings()
    previous = settings.exchange_static_ip
    settings.exchange_static_ip = SIM_SERVER_IP
    yield adapter
    settings.exchange_static_ip = previous
    bot_routes.set_trading_adapter(None)


async def auth(client: AsyncClient, prefix: str) -> dict[str, str]:
    await register(client, prefix)
    tokens = await login(client, prefix)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def current_user(db: AsyncSession) -> User:
    result = await db.execute(select(User))
    return result.scalars().first()  # type: ignore[return-value]


async def enable_2fa(db: AsyncSession) -> str:
    """Turn on 2FA and return a currently valid code."""
    user = await current_user(db)
    user.totp_secret = pyotp.random_base32()
    user.totp_enabled = True
    user.last_totp_counter = None
    await db.commit()
    assert user.totp_secret is not None
    return pyotp.TOTP(user.totp_secret).now()


async def fresh_code(db: AsyncSession) -> str:
    """A code the replay guard has not seen yet.

    verify_second_factor refuses a counter it already used, so a test that
    needs two codes has to step the clock rather than send the same one.
    """
    user = await current_user(db)
    user.last_totp_counter = None
    await db.commit()
    assert user.totp_secret is not None
    return pyotp.TOTP(user.totp_secret).now()


async def add_key(client: AsyncClient, prefix: str, headers: dict[str, str], **over) -> dict:
    payload = {
        "label": "Main",
        "exchange": "bitunix",
        "api_key": API_KEY,
        "api_secret": API_SECRET,
    }
    payload.update(over)
    response = await client.post(f"{prefix}/exchange-keys", headers=headers, json=payload)
    return (
        response.json()
        if response.status_code < 400
        else {"_status": response.status_code, **response.json()}
    )


async def make_setup(
    client: AsyncClient,
    prefix: str,
    headers: dict[str, str],
    db: AsyncSession,
    *,
    promoted: bool = True,
) -> Setup:
    """A Setup with a real strategy behind it, as the column requires."""
    strategy_id = await make_strategy(client, prefix, headers)
    user = await current_user(db)
    setup = Setup(
        user_id=user.id,
        name="Momentum",
        strategy_id=uuid.UUID(strategy_id),
        strategy_version="v1",
        symbol=SYMBOL,
        interval="1h",
        leverage=10,
        margin_percent=5,
        maker_fee=0.0002,
        taker_fee=0.0006,
        use_in_bot=promoted,
    )
    db.add(setup)
    await db.commit()
    await db.refresh(setup)
    return setup


async def make_bot(
    client: AsyncClient, prefix: str, headers: dict[str, str], db: AsyncSession, **over
) -> dict:
    key = await add_key(client, prefix, headers)
    setup = await make_setup(client, prefix, headers, db, promoted=over.pop("promoted", True))
    payload = {
        "name": "BTC bot",
        "setup_id": str(setup.id),
        "exchange_key_id": key["id"],
        "symbol": SYMBOL,
        "interval": "1h",
        "leverage": 10,
        "margin_mode": "ISOLATED",
        "position_mode": "ONE_WAY",
        "limits": LIMITS,
    }
    payload.update(over)
    response = await client.post(f"{prefix}/bots", headers=headers, json=payload)
    return response.json()


class TestKeySecrecy:
    async def test_the_secret_never_comes_back(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        created = await add_key(client, api_prefix, headers)
        assert API_SECRET not in str(created)
        assert API_KEY not in str(created)

        listed = await client.get(f"{api_prefix}/exchange-keys", headers=headers)
        assert API_SECRET not in listed.text
        assert API_KEY not in listed.text

    async def test_only_the_tail_and_a_fingerprint_are_shown(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        created = await add_key(client, api_prefix, headers)
        assert created["last_four"] == API_KEY[-4:]
        assert len(created["fingerprint"]) == 16

    async def test_the_stored_row_holds_no_plaintext(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await add_key(client, api_prefix, headers)

        row = (await db.execute(select(ExchangeKey))).scalars().one()
        blob = row.api_key_sealed + row.api_secret_sealed
        assert API_KEY.encode() not in blob
        assert API_SECRET.encode() not in blob

    async def test_the_key_can_still_be_opened_by_the_server(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await add_key(client, api_prefix, headers)

        row = (await db.execute(select(ExchangeKey))).scalars().one()
        credentials = bot_service.open_key(KeyVault.local(get_settings()), row)
        assert credentials.api_key == API_KEY
        assert credentials.api_secret == API_SECRET


class TestKeyAdmission:
    async def test_a_withdrawal_key_is_refused_with_a_reason(
        self, client: AsyncClient, api_prefix: str, venue: SimulatedTradingAdapter
    ) -> None:
        venue.add_account(
            "bad-key-0001",
            SimAccount(
                permissions=KeyPermissions(
                    can_read=True,
                    can_trade=True,
                    can_withdraw=True,
                    ip_whitelist=(SIM_SERVER_IP,),
                )
            ),
        )
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/exchange-keys",
            headers=headers,
            json={
                "label": "Bad",
                "exchange": "bitunix",
                "api_key": "bad-key-0001",
                "api_secret": API_SECRET,
            },
        )
        assert response.status_code == 400
        assert "withdraw" in response.json()["detail"].lower()

    async def test_a_key_not_whitelisted_is_refused_and_names_the_ip(
        self, client: AsyncClient, api_prefix: str, venue: SimulatedTradingAdapter
    ) -> None:
        venue.add_account(
            "elsewhere",
            SimAccount(permissions=default_permissions(whitelist_ip="198.51.100.4")),
        )
        headers = await auth(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/exchange-keys",
            headers=headers,
            json={
                "label": "Elsewhere",
                "exchange": "bitunix",
                "api_key": "elsewhere",
                "api_secret": API_SECRET,
            },
        )
        assert response.status_code == 400
        assert SIM_SERVER_IP in response.json()["detail"]

    async def test_the_server_ip_is_returned_with_the_list(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        """The page shows it above the form, before a key is pasted."""
        headers = await auth(client, api_prefix)
        response = await client.get(f"{api_prefix}/exchange-keys", headers=headers)
        assert response.json()["server_ip"] == SIM_SERVER_IP

    async def test_a_duplicate_label_is_refused(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        await add_key(client, api_prefix, headers)
        again = await add_key(client, api_prefix, headers)
        assert again["_status"] == 409


class TestKeyDeletion:
    async def test_a_key_in_use_cannot_be_deleted(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        response = await client.delete(
            f"{api_prefix}/exchange-keys/{bot['exchange_key_id']}", headers=headers
        )
        assert response.status_code == 409
        # It names the bot, so the user knows what to do next.
        assert "BTC bot" in response.json()["detail"]

    async def test_an_unused_key_deletes(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth(client, api_prefix)
        key = await add_key(client, api_prefix, headers)
        response = await client.delete(f"{api_prefix}/exchange-keys/{key['id']}", headers=headers)
        assert response.status_code == 204

    async def test_another_users_key_is_not_visible(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth(client, api_prefix)
        key = await add_key(client, api_prefix, headers)

        await register(client, api_prefix, email="other@example.com")
        other = await login(client, api_prefix, email="other@example.com")
        response = await client.delete(
            f"{api_prefix}/exchange-keys/{key['id']}",
            headers={"Authorization": f"Bearer {other['access_token']}"},
        )
        assert response.status_code == 404


class TestPreflight:
    async def test_a_promoted_setup_with_2fa_is_ready(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        await enable_2fa(db)

        response = await client.get(f"{api_prefix}/bots/{bot['id']}/preflight", headers=headers)
        body = response.json()
        assert body["ready"], body["blocking"]

    async def test_a_setup_that_has_not_passed_paper_blocks(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db, promoted=False)
        await enable_2fa(db)

        body = (
            await client.get(f"{api_prefix}/bots/{bot['id']}/preflight", headers=headers)
        ).json()
        assert not body["ready"]
        assert "Passed paper trading" in body["blocking"]

    async def test_no_2fa_blocks(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        body = (
            await client.get(f"{api_prefix}/bots/{bot['id']}/preflight", headers=headers)
        ).json()
        assert "2FA is on" in body["blocking"]

    async def test_every_check_carries_the_figure_it_was_judged_on(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        """A checklist that says "failed" without the number cannot be
        acted on."""
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        body = (
            await client.get(f"{api_prefix}/bots/{bot['id']}/preflight", headers=headers)
        ).json()
        assert all(check["detail"] for check in body["checks"])


class TestArming:
    async def test_arming_needs_a_code(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        await enable_2fa(db)

        response = await client.post(
            f"{api_prefix}/bots/{bot['id']}/arm", headers=headers, json={"code": "000000"}
        )
        assert response.status_code == 401

    async def test_arming_without_2fa_enabled_is_refused(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        response = await client.post(
            f"{api_prefix}/bots/{bot['id']}/arm", headers=headers, json={"code": "123456"}
        )
        assert response.status_code == 403
        assert "Settings" in response.json()["detail"]

    async def test_a_good_code_and_a_clean_preflight_arms(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        code = await enable_2fa(db)

        response = await client.post(
            f"{api_prefix}/bots/{bot['id']}/arm", headers=headers, json={"code": code}
        )
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "armed"

    async def test_a_failing_preflight_refuses_even_with_a_good_code(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db, promoted=False)
        code = await enable_2fa(db)

        response = await client.post(
            f"{api_prefix}/bots/{bot['id']}/arm", headers=headers, json={"code": code}
        )
        assert response.status_code == 409
        assert "paper" in response.json()["detail"].lower()

    async def test_stopping_needs_no_code(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        """Stopping is always allowed to be easy."""
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        code = await enable_2fa(db)
        await client.post(
            f"{api_prefix}/bots/{bot['id']}/arm", headers=headers, json={"code": code}
        )

        response = await client.post(f"{api_prefix}/bots/{bot['id']}/stop", headers=headers)
        assert response.status_code == 200
        assert response.json()["state"] == "stopped"


class TestHalts:
    async def test_a_halted_bot_cannot_be_armed(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        created = await make_bot(client, api_prefix, headers, db)
        code = await enable_2fa(db)

        bot = await db.get(Bot, uuid.UUID(created["id"]))
        assert bot is not None
        bot_service.halt(bot, "daily_loss", "Down 700 today against a limit of 500.")
        await db.commit()

        response = await client.post(
            f"{api_prefix}/bots/{created['id']}/arm", headers=headers, json={"code": code}
        )
        assert response.status_code == 409
        # The reason travels with the refusal.
        assert "700" in response.json()["detail"]

    async def test_clearing_a_halt_returns_it_to_stopped_not_armed(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        created = await make_bot(client, api_prefix, headers, db)
        bot = await db.get(Bot, uuid.UUID(created["id"]))
        assert bot is not None
        bot_service.halt(bot, "max_drawdown", "Down 30% from its peak.")
        await db.commit()

        response = await client.post(
            f"{api_prefix}/bots/{created['id']}/clear-halt", headers=headers
        )
        assert response.json()["state"] == "stopped"
        assert response.json()["halt_reason"] is None

    async def test_clearing_a_bot_that_did_not_halt_is_refused(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        response = await client.post(f"{api_prefix}/bots/{bot['id']}/clear-halt", headers=headers)
        assert response.status_code == 409


class TestLimitChanges:
    async def test_lowering_a_limit_needs_no_code(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        """Making yourself safer is not gated behind a phone."""
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        response = await client.patch(
            f"{api_prefix}/bots/{bot['id']}",
            headers=headers,
            json={"limits": {**LIMITS, "max_daily_loss": "200"}},
        )
        assert response.status_code == 200
        assert response.json()["limits"]["max_daily_loss"] == 200.0

    async def test_raising_a_limit_needs_a_code(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        await enable_2fa(db)
        response = await client.patch(
            f"{api_prefix}/bots/{bot['id']}",
            headers=headers,
            json={"limits": {**LIMITS, "max_daily_loss": "5000"}},
        )
        assert response.status_code == 401

    async def test_raising_a_limit_with_a_code_works(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        code = await enable_2fa(db)
        response = await client.patch(
            f"{api_prefix}/bots/{bot['id']}",
            headers=headers,
            json={"limits": {**LIMITS, "max_daily_loss": "5000"}, "code": code},
        )
        assert response.status_code == 200

    async def test_a_running_bot_cannot_be_edited(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        created = await make_bot(client, api_prefix, headers, db)
        code = await enable_2fa(db)
        await client.post(
            f"{api_prefix}/bots/{created['id']}/arm", headers=headers, json={"code": code}
        )
        response = await client.patch(
            f"{api_prefix}/bots/{created['id']}", headers=headers, json={"name": "Renamed"}
        )
        assert response.status_code == 409


class TestKillSwitch:
    async def test_it_needs_an_explicit_confirmation(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await make_bot(client, api_prefix, headers, db)
        code = await enable_2fa(db)

        response = await client.post(
            f"{api_prefix}/bots/kill",
            headers=headers,
            json={"code": code, "confirm_flatten": False},
        )
        assert response.status_code == 400
        assert "market" in response.json()["detail"]

    async def test_it_needs_2fa(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        await make_bot(client, api_prefix, headers, db)
        await enable_2fa(db)

        response = await client.post(
            f"{api_prefix}/bots/kill",
            headers=headers,
            json={"code": "000000", "confirm_flatten": True},
        )
        assert response.status_code == 401

    async def test_it_halts_every_bot(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        created = await make_bot(client, api_prefix, headers, db)
        code = await enable_2fa(db)

        response = await client.post(
            f"{api_prefix}/bots/kill",
            headers=headers,
            json={"code": code, "confirm_flatten": True},
        )
        assert response.status_code == 200, response.text
        assert response.json()["bots_halted"] == 1

        listed = (await client.get(f"{api_prefix}/bots", headers=headers)).json()
        assert listed[0]["state"] == "halted"
        assert listed[0]["halt_reason"] == "kill_switch"
        assert created["id"] == listed[0]["id"]

    async def test_it_closes_an_open_position(
        self,
        client: AsyncClient,
        api_prefix: str,
        db: AsyncSession,
        venue: SimulatedTradingAdapter,
    ) -> None:
        headers = await auth(client, api_prefix)
        await make_bot(client, api_prefix, headers, db)
        code = await enable_2fa(db)

        from quanta.exchanges.trading import Credentials

        credentials = Credentials(api_key=API_KEY, api_secret=API_SECRET)
        await venue.place_order(
            credentials,
            OrderRequest(
                symbol=SYMBOL,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                qty=Decimal(1),
                client_id="seeded",
            ),
        )
        assert await venue.positions(credentials) != []

        response = await client.post(
            f"{api_prefix}/bots/kill",
            headers=headers,
            json={"code": code, "confirm_flatten": True},
        )
        assert response.json()["positions_closed"] == 1
        assert await venue.positions(credentials) == []


class TestOrdersLog:
    async def test_an_empty_log_is_an_empty_list(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)
        response = await client.get(f"{api_prefix}/bots/{bot['id']}/orders", headers=headers)
        assert response.json() == []

    async def test_another_users_bot_is_not_readable(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        headers = await auth(client, api_prefix)
        bot = await make_bot(client, api_prefix, headers, db)

        await register(client, api_prefix, email="other@example.com")
        other = await login(client, api_prefix, email="other@example.com")
        response = await client.get(
            f"{api_prefix}/bots/{bot['id']}/orders",
            headers={"Authorization": f"Bearer {other['access_token']}"},
        )
        assert response.status_code == 404


class TestAudit:
    async def test_adding_a_key_records_the_fingerprint_not_the_key(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession
    ) -> None:
        from quanta.models.audit import AuditEvent

        headers = await auth(client, api_prefix)
        await add_key(client, api_prefix, headers)

        rows = (
            (await db.execute(select(AuditEvent).where(AuditEvent.action == "exchange_key.added")))
            .scalars()
            .all()
        )
        assert rows
        assert API_SECRET not in str(rows[0].detail)
        assert API_KEY not in str(rows[0].detail)
        assert rows[0].detail["fingerprint"]

    async def test_a_rejected_key_is_recorded_with_its_reason(
        self, client: AsyncClient, api_prefix: str, db: AsyncSession, venue
    ) -> None:
        from quanta.models.audit import AuditEvent

        venue.add_account(
            "rejected-key",
            SimAccount(
                permissions=KeyPermissions(
                    can_read=True,
                    can_trade=True,
                    can_withdraw=True,
                    ip_whitelist=(SIM_SERVER_IP,),
                )
            ),
        )
        headers = await auth(client, api_prefix)
        await client.post(
            f"{api_prefix}/exchange-keys",
            headers=headers,
            json={
                "label": "Rejected",
                "exchange": "bitunix",
                "api_key": "rejected-key",
                "api_secret": API_SECRET,
            },
        )
        rows = (
            (
                await db.execute(
                    select(AuditEvent).where(AuditEvent.action == "exchange_key.rejected")
                )
            )
            .scalars()
            .all()
        )
        assert rows
        assert rows[0].detail["reason"] == "withdrawal_permission"
