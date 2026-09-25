"""End-to-end tests for the authentication flow."""

from __future__ import annotations

import pyotp
import pytest
from httpx import AsyncClient

GOOD_PASSWORD = "Sunset-Harbour-42!"


async def register(client: AsyncClient, prefix: str, email: str = "trader@example.com") -> dict:
    response = await client.post(
        f"{prefix}/auth/register",
        json={"email": email, "display_name": "Test Trader", "password": GOOD_PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def login(client: AsyncClient, prefix: str, email: str = "trader@example.com") -> dict:
    response = await client.post(
        f"{prefix}/auth/login", json={"email": email, "password": GOOD_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestRegistration:
    async def test_creates_an_account(self, client: AsyncClient, api_prefix: str) -> None:
        body = await register(client, api_prefix)
        assert body["email"] == "trader@example.com"
        assert body["totp_enabled"] is False
        # The hash must never be serialised.
        assert "password" not in body
        assert "password_hash" not in body

    async def test_rejects_a_duplicate_email(self, client: AsyncClient, api_prefix: str) -> None:
        await register(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/auth/register",
            json={
                "email": "trader@example.com",
                "display_name": "Someone Else",
                "password": GOOD_PASSWORD,
            },
        )
        assert response.status_code == 409

    @pytest.mark.parametrize(
        "password",
        ["short1!A", "alllowercase1!", "ALLUPPERCASE1!", "NoDigitsHere!!", "NoSymbols123ABC"],
    )
    async def test_rejects_weak_passwords(
        self, client: AsyncClient, api_prefix: str, password: str
    ) -> None:
        response = await client.post(
            f"{api_prefix}/auth/register",
            json={"email": "weak@example.com", "display_name": "W", "password": password},
        )
        assert response.status_code == 422


class TestLogin:
    async def test_returns_tokens_and_cookies(self, client: AsyncClient, api_prefix: str) -> None:
        await register(client, api_prefix)
        body = await login(client, api_prefix)

        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 15 * 60
        assert body["user"]["email"] == "trader@example.com"
        assert "quanta_refresh" in client.cookies
        assert body["csrf_token"]

    async def test_wrong_password_is_rejected(self, client: AsyncClient, api_prefix: str) -> None:
        await register(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/auth/login",
            json={"email": "trader@example.com", "password": "Wrong-Password-1!"},
        )
        assert response.status_code == 401

    async def test_unknown_email_gives_the_same_error(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        """Account existence must not leak through the error message."""
        await register(client, api_prefix)
        unknown = await client.post(
            f"{api_prefix}/auth/login",
            json={"email": "nobody@example.com", "password": GOOD_PASSWORD},
        )
        wrong = await client.post(
            f"{api_prefix}/auth/login",
            json={"email": "trader@example.com", "password": "Wrong-Password-1!"},
        )
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["detail"] == wrong.json()["detail"]


class TestProtectedRoutes:
    async def test_me_requires_a_token(self, client: AsyncClient, api_prefix: str) -> None:
        assert (await client.get(f"{api_prefix}/users/me")).status_code == 401

    async def test_me_returns_the_account(self, client: AsyncClient, api_prefix: str) -> None:
        await register(client, api_prefix)
        tokens = await login(client, api_prefix)
        response = await client.get(
            f"{api_prefix}/users/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert response.status_code == 200
        assert response.json()["email"] == "trader@example.com"

    async def test_garbage_token_is_rejected(self, client: AsyncClient, api_prefix: str) -> None:
        response = await client.get(
            f"{api_prefix}/users/me", headers={"Authorization": "Bearer not.a.token"}
        )
        assert response.status_code == 401

    async def test_preferences_round_trip(self, client: AsyncClient, api_prefix: str) -> None:
        await register(client, api_prefix)
        tokens = await login(client, api_prefix)
        response = await client.patch(
            f"{api_prefix}/users/me/preferences",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            json={"theme": "paper", "locale": "fa", "calendar": "jalali"},
        )
        assert response.status_code == 200
        body = response.json()
        assert (body["theme"], body["locale"], body["calendar"]) == ("paper", "fa", "jalali")

    async def test_unknown_theme_is_rejected(self, client: AsyncClient, api_prefix: str) -> None:
        await register(client, api_prefix)
        tokens = await login(client, api_prefix)
        response = await client.patch(
            f"{api_prefix}/users/me/preferences",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            json={"theme": "neon"},
        )
        assert response.status_code == 422


class TestRefreshRotation:
    async def test_refresh_rotates_the_cookie(self, client: AsyncClient, api_prefix: str) -> None:
        await register(client, api_prefix)
        await login(client, api_prefix)
        first = client.cookies["quanta_refresh"]

        response = await client.post(f"{api_prefix}/auth/refresh")
        assert response.status_code == 200
        assert client.cookies["quanta_refresh"] != first

    async def test_replaying_an_old_token_fails(self, client: AsyncClient, api_prefix: str) -> None:
        await register(client, api_prefix)
        await login(client, api_prefix)
        stolen = client.cookies["quanta_refresh"]

        assert (await client.post(f"{api_prefix}/auth/refresh")).status_code == 200

        # Replace the jar wholesale: setting a cookie with an explicit domain
        # would add a second entry rather than shadow the rotated one.
        client.cookies.clear()
        client.cookies.set("quanta_refresh", stolen)
        assert (await client.post(f"{api_prefix}/auth/refresh")).status_code == 401

    async def test_refresh_without_a_cookie_fails(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        assert (await client.post(f"{api_prefix}/auth/refresh")).status_code == 401


class TestCsrf:
    async def test_logout_requires_the_csrf_header(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        await register(client, api_prefix)
        await login(client, api_prefix)
        assert (await client.post(f"{api_prefix}/auth/logout")).status_code == 403

    async def test_logout_with_the_header_revokes_the_session(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        await register(client, api_prefix)
        tokens = await login(client, api_prefix)

        response = await client.post(
            f"{api_prefix}/auth/logout", headers={"X-CSRF-Token": tokens["csrf_token"]}
        )
        assert response.status_code == 204
        assert (await client.post(f"{api_prefix}/auth/refresh")).status_code == 401

    async def test_mismatched_csrf_token_is_rejected(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        await register(client, api_prefix)
        await login(client, api_prefix)
        response = await client.post(
            f"{api_prefix}/auth/logout", headers={"X-CSRF-Token": "not-the-cookie-value"}
        )
        assert response.status_code == 403


class TestTwoFactor:
    async def test_full_enrolment_and_mfa_login(self, client: AsyncClient, api_prefix: str) -> None:
        await register(client, api_prefix)
        tokens = await login(client, api_prefix)
        auth = {"Authorization": f"Bearer {tokens['access_token']}"}

        start = await client.post(f"{api_prefix}/auth/totp/start", headers=auth)
        assert start.status_code == 200
        secret = start.json()["secret"]
        assert "<svg" in start.json()["qr_svg"]

        confirm = await client.post(
            f"{api_prefix}/auth/totp/confirm",
            headers=auth,
            json={"code": pyotp.TOTP(secret).now()},
        )
        assert confirm.status_code == 200
        recovery_codes = confirm.json()["recovery_codes"]
        assert len(recovery_codes) == 10

        # A fresh login must now stop at the MFA step.
        step_one = await client.post(
            f"{api_prefix}/auth/login",
            json={"email": "trader@example.com", "password": GOOD_PASSWORD},
        )
        assert step_one.status_code == 200
        assert step_one.json()["mfa_required"] is True
        ticket = step_one.json()["ticket"]

        step_two = await client.post(
            f"{api_prefix}/auth/login/mfa",
            json={"ticket": ticket, "code": pyotp.TOTP(secret).now()},
        )
        assert step_two.status_code == 200
        assert step_two.json()["user"]["totp_enabled"] is True

    async def test_wrong_totp_code_is_rejected(self, client: AsyncClient, api_prefix: str) -> None:
        await register(client, api_prefix)
        tokens = await login(client, api_prefix)
        auth = {"Authorization": f"Bearer {tokens['access_token']}"}

        secret = (await client.post(f"{api_prefix}/auth/totp/start", headers=auth)).json()["secret"]
        await client.post(
            f"{api_prefix}/auth/totp/confirm",
            headers=auth,
            json={"code": pyotp.TOTP(secret).now()},
        )

        ticket = (
            await client.post(
                f"{api_prefix}/auth/login",
                json={"email": "trader@example.com", "password": GOOD_PASSWORD},
            )
        ).json()["ticket"]

        response = await client.post(
            f"{api_prefix}/auth/login/mfa", json={"ticket": ticket, "code": "000000"}
        )
        assert response.status_code == 401

    async def test_a_recovery_code_works_once(self, client: AsyncClient, api_prefix: str) -> None:
        await register(client, api_prefix)
        tokens = await login(client, api_prefix)
        auth = {"Authorization": f"Bearer {tokens['access_token']}"}

        secret = (await client.post(f"{api_prefix}/auth/totp/start", headers=auth)).json()["secret"]
        codes = (
            await client.post(
                f"{api_prefix}/auth/totp/confirm",
                headers=auth,
                json={"code": pyotp.TOTP(secret).now()},
            )
        ).json()["recovery_codes"]

        async def ticket_for_login() -> str:
            response = await client.post(
                f"{api_prefix}/auth/login",
                json={"email": "trader@example.com", "password": GOOD_PASSWORD},
            )
            return str(response.json()["ticket"])

        first = await client.post(
            f"{api_prefix}/auth/login/mfa",
            json={"ticket": await ticket_for_login(), "code": codes[0]},
        )
        assert first.status_code == 200

        # The same code must not work a second time.
        second = await client.post(
            f"{api_prefix}/auth/login/mfa",
            json={"ticket": await ticket_for_login(), "code": codes[0]},
        )
        assert second.status_code == 401

    async def test_an_mfa_ticket_is_not_an_access_token(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        await register(client, api_prefix)
        tokens = await login(client, api_prefix)
        auth = {"Authorization": f"Bearer {tokens['access_token']}"}
        secret = (await client.post(f"{api_prefix}/auth/totp/start", headers=auth)).json()["secret"]
        await client.post(
            f"{api_prefix}/auth/totp/confirm",
            headers=auth,
            json={"code": pyotp.TOTP(secret).now()},
        )
        ticket = (
            await client.post(
                f"{api_prefix}/auth/login",
                json={"email": "trader@example.com", "password": GOOD_PASSWORD},
            )
        ).json()["ticket"]

        response = await client.get(
            f"{api_prefix}/users/me", headers={"Authorization": f"Bearer {ticket}"}
        )
        assert response.status_code == 401


class TestSessions:
    async def test_revoke_all_ends_every_session(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        await register(client, api_prefix)
        tokens = await login(client, api_prefix)

        listed = await client.get(
            f"{api_prefix}/auth/sessions",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        revoked = await client.post(
            f"{api_prefix}/auth/sessions/revoke-all",
            headers={
                "Authorization": f"Bearer {tokens['access_token']}",
                "X-CSRF-Token": tokens["csrf_token"],
            },
        )
        assert revoked.status_code == 204
        assert (await client.post(f"{api_prefix}/auth/refresh")).status_code == 401
