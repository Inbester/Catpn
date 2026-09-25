"""Authentication routes: register, login, 2FA, refresh, logout."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Annotated, Any

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from quanta.api.deps import (
    CurrentUser,
    DbDep,
    SettingsDep,
    auth_rate_limit,
    client_ip,
    verify_csrf,
)
from quanta.core.config import Settings
from quanta.core.security import (
    TokenError,
    create_access_token,
    create_mfa_ticket,
    decode_token,
    generate_csrf_token,
    verify_password,
)
from quanta.schemas.auth import (
    LoginRequest,
    MfaRequiredResponse,
    MfaVerifyRequest,
    RegisterRequest,
    SessionResponse,
    TokenResponse,
    TotpDisableRequest,
    TotpEnrolConfirmRequest,
    TotpEnrolConfirmResponse,
    TotpEnrolStartResponse,
    UserResponse,
)
from quanta.services import auth_service
from quanta.services.auth_service import AuthError

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookies(response: Response, settings: Settings, refresh_token: str) -> str:
    """Attach the refresh + CSRF cookies and return the CSRF token."""
    max_age = settings.refresh_token_ttl_days * 24 * 3600
    response.set_cookie(
        settings.refresh_cookie_name,
        refresh_token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=f"{settings.api_prefix}/auth",
        domain=settings.cookie_domain,
    )
    csrf_token = generate_csrf_token()
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        # Readable by JS on purpose — this is the double-submit half.
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
        domain=settings.cookie_domain,
    )
    return csrf_token


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.refresh_cookie_name,
        path=f"{settings.api_prefix}/auth",
        domain=settings.cookie_domain,
    )
    response.delete_cookie(settings.csrf_cookie_name, path="/", domain=settings.cookie_domain)


async def _complete_login(
    db: Any,
    request: Request,
    response: Response,
    settings: Settings,
    user: Any,
    device_label: str | None,
) -> TokenResponse:
    """Issue the token pair once every factor has passed."""
    refresh_token, _session = await auth_service.issue_refresh_token(
        db,
        user,
        user_agent=request.headers.get("User-Agent"),
        ip_address=client_ip(request),
        device_label=device_label,
    )
    user.last_login_at = datetime.now(UTC)
    await auth_service.record_audit(
        db,
        "auth.login",
        user_id=user.id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("User-Agent"),
    )
    await db.commit()
    await db.refresh(user)

    csrf_token = _set_auth_cookies(response, settings, refresh_token)
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_ttl_minutes * 60,
        csrf_token=csrf_token,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(auth_rate_limit)],
)
async def register(payload: RegisterRequest, request: Request, db: DbDep) -> UserResponse:
    """Create an account."""
    try:
        user = await auth_service.register_user(
            db, payload.email, payload.display_name, payload.password
        )
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    await auth_service.record_audit(
        db, "auth.register", user_id=user.id, ip_address=client_ip(request)
    )
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse | MfaRequiredResponse,
    dependencies=[Depends(auth_rate_limit)],
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
) -> TokenResponse | MfaRequiredResponse:
    """Step 1: email and password. Returns a ticket when 2FA is on."""
    try:
        user = await auth_service.authenticate(db, payload.email, payload.password)
    except AuthError as exc:
        await auth_service.record_audit(
            db,
            "auth.login",
            outcome="failure",
            detail={"email": payload.email.lower()},
            ip_address=client_ip(request),
            user_agent=request.headers.get("User-Agent"),
        )
        await db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    if user.totp_enabled:
        await db.commit()
        return MfaRequiredResponse(
            ticket=create_mfa_ticket(user.id),
            expires_in=settings.mfa_ticket_ttl_seconds,
        )

    return await _complete_login(db, request, response, settings, user, payload.device_label)


@router.post(
    "/login/mfa",
    response_model=TokenResponse,
    dependencies=[Depends(auth_rate_limit)],
)
async def login_mfa(
    payload: MfaVerifyRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
) -> TokenResponse:
    """Step 2: the TOTP or recovery code."""
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="That code is not valid."
    )
    try:
        claims = decode_token(payload.ticket, "mfa")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This sign-in attempt expired. Please start again.",
        ) from exc

    import uuid as _uuid

    user = await auth_service.get_user_by_id(db, _uuid.UUID(claims["sub"]))
    if user is None or not user.is_active:
        raise invalid

    if not auth_service.verify_second_factor(user, payload.code):
        await auth_service.record_audit(
            db,
            "auth.mfa",
            user_id=user.id,
            outcome="failure",
            ip_address=client_ip(request),
        )
        await db.commit()
        raise invalid

    return await _complete_login(db, request, response, settings, user, payload.device_label)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request, response: Response, db: DbDep, settings: SettingsDep
) -> TokenResponse:
    """Rotate the refresh cookie and mint a new access token."""
    presented = request.cookies.get(settings.refresh_cookie_name)
    if not presented:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No active session.")

    try:
        new_token, user = await auth_service.rotate_refresh_token(
            db, presented, ip_address=client_ip(request)
        )
    except AuthError as exc:
        await db.commit()
        _clear_auth_cookies(response, settings)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    await db.commit()
    csrf_token = _set_auth_cookies(response, settings, new_token)
    return TokenResponse(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_ttl_minutes * 60,
        csrf_token=csrf_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    _: Annotated[None, Depends(verify_csrf)],
) -> Response:
    """Revoke the current session."""
    presented = request.cookies.get(settings.refresh_cookie_name)
    if presented:
        await auth_service.revoke_session(db, presented)
        await db.commit()
    _clear_auth_cookies(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(user: CurrentUser, db: DbDep) -> list[SessionResponse]:
    """Active sessions for the account page."""
    sessions = await auth_service.list_sessions(db, user.id)
    return [SessionResponse.model_validate(s) for s in sessions]


@router.post("/sessions/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_sessions(
    user: CurrentUser,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    _: Annotated[None, Depends(verify_csrf)],
) -> Response:
    """Sign out on every device."""
    await auth_service.revoke_all_sessions(db, user.id)
    await auth_service.record_audit(db, "auth.revoke_all", user_id=user.id)
    await db.commit()
    _clear_auth_cookies(response, settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


# --- TOTP enrolment --------------------------------------------------------


@router.post("/totp/start", response_model=TotpEnrolStartResponse)
async def totp_start(user: CurrentUser, db: DbDep) -> TotpEnrolStartResponse:
    """Begin 2FA enrolment: returns the secret, URI and a QR code."""
    if user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Two-factor authentication is already enabled.",
        )

    from quanta.core.security import totp_provisioning_uri

    secret = auth_service.start_totp_enrolment(user)
    await db.commit()

    uri = totp_provisioning_uri(secret, user.email)
    buffer = io.BytesIO()
    qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).save(buffer)

    return TotpEnrolStartResponse(
        secret=secret, provisioning_uri=uri, qr_svg=buffer.getvalue().decode("utf-8")
    )


@router.post("/totp/confirm", response_model=TotpEnrolConfirmResponse)
async def totp_confirm(
    payload: TotpEnrolConfirmRequest, user: CurrentUser, db: DbDep
) -> TotpEnrolConfirmResponse:
    """Confirm enrolment with a code and receive the recovery codes."""
    try:
        codes = auth_service.confirm_totp_enrolment(user, payload.code)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    await auth_service.record_audit(db, "auth.totp_enabled", user_id=user.id)
    await db.commit()
    return TotpEnrolConfirmResponse(recovery_codes=codes)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
async def totp_disable(
    payload: TotpDisableRequest, user: CurrentUser, db: DbDep, response: Response
) -> Response:
    """Turn 2FA off. Requires the password *and* a current code."""
    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication is not enabled.",
        )
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password.")
    if not auth_service.verify_second_factor(user, payload.code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="That code is not valid."
        )

    user.totp_enabled = False
    user.totp_secret = None
    user.totp_pending_secret = None
    user.recovery_code_hashes = []
    user.last_totp_counter = None
    await auth_service.record_audit(db, "auth.totp_disabled", user_id=user.id)
    await db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
