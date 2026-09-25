"""Authentication workflows: registration, login, refresh rotation, TOTP."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pyotp
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from quanta.core.config import get_settings
from quanta.core.security import (
    constant_time_compare,
    generate_recovery_codes,
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
    verify_totp,
)
from quanta.models.audit import AuditEvent
from quanta.models.user import AuthSession, User

# How long a just-rotated refresh token keeps working. Long enough to cover
# concurrent refreshes from two tabs or a retried request, short enough that a
# stolen token is useless: outside this window a reused token is treated as
# theft and every session for that user is revoked.
REFRESH_GRACE_SECONDS = 15


class AuthError(Exception):
    """A failed authentication step, safe to surface to the client."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def record_audit(
    db: AsyncSession,
    action: str,
    *,
    user_id: uuid.UUID | None = None,
    outcome: str = "success",
    detail: dict[str, object] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Append one row to the audit log. Never stores secrets."""
    db.add(
        AuditEvent(
            user_id=user_id,
            action=action,
            outcome=outcome,
            detail=detail or {},
            ip_address=ip_address,
            user_agent=user_agent[:400] if user_agent else None,
        )
    )


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower().strip()))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def register_user(db: AsyncSession, email: str, display_name: str, password: str) -> User:
    """Create an account. Raises :class:`AuthError` if the email is taken."""
    normalized = email.lower().strip()
    if await get_user_by_email(db, normalized) is not None:
        raise AuthError("An account with this email already exists.", status_code=409)

    user = User(
        email=normalized,
        display_name=display_name,
        password_hash=hash_password(password),
    )
    db.add(user)
    await db.flush()
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    """Check email + password.

    The same error text is used for an unknown email and a wrong password so
    the endpoint does not leak which accounts exist.
    """
    user = await get_user_by_email(db, email)
    if user is None:
        # Spend roughly the same time as a real verify to blunt timing probes.
        hash_password(password)
        raise AuthError("Incorrect email or password.")

    if not verify_password(password, user.password_hash):
        raise AuthError("Incorrect email or password.")

    if not user.is_active:
        raise AuthError("This account is disabled.", status_code=403)

    # Transparently upgrade hashes when the Argon2 policy gets stronger.
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    return user


def verify_second_factor(user: User, code: str) -> bool:
    """Verify a TOTP code or burn a recovery code.

    Returns ``True`` on success. Mutates ``user`` when a recovery code is used
    or when the TOTP replay counter advances; the caller commits.
    """
    if not user.totp_enabled or not user.totp_secret:
        return False

    cleaned = code.strip().replace(" ", "").replace("-", "")

    if len(cleaned) == 6 and cleaned.isdigit():
        if not verify_totp(user.totp_secret, cleaned):
            return False
        # Reject a code that was already spent inside the same 30s window.
        counter = pyotp.TOTP(user.totp_secret).timecode(datetime.now(UTC))
        if user.last_totp_counter is not None and counter <= user.last_totp_counter:
            return False
        user.last_totp_counter = counter
        return True

    # Otherwise treat it as a single-use recovery code.
    supplied_hash = hash_token(code.strip().lower())
    for stored in user.recovery_code_hashes:
        if constant_time_compare(stored, supplied_hash):
            user.recovery_code_hashes = [
                h for h in user.recovery_code_hashes if not constant_time_compare(h, supplied_hash)
            ]
            return True
    return False


async def issue_refresh_token(
    db: AsyncSession,
    user: User,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
    device_label: str | None = None,
) -> tuple[str, AuthSession]:
    """Create a session row and return the plaintext refresh token once."""
    settings = get_settings()
    token = generate_token()
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
        user_agent=user_agent[:400] if user_agent else None,
        ip_address=ip_address,
        device_label=device_label,
    )
    db.add(session)
    await db.flush()
    return token, session


async def rotate_refresh_token(
    db: AsyncSession, presented_token: str, *, ip_address: str | None = None
) -> tuple[str, User]:
    """Exchange a refresh token for a new one.

    Rotation is mandatory: the presented token's hash is replaced, so a stolen
    copy replayed afterwards matches nothing and is rejected.
    """
    token_hash = hash_token(presented_token)
    now = datetime.now(UTC)

    result = await db.execute(
        select(AuthSession).where(
            or_(
                AuthSession.token_hash == token_hash,
                AuthSession.previous_token_hash == token_hash,
            )
        )
    )
    session = result.scalar_one_or_none()

    if session is None:
        raise AuthError("Invalid session. Please sign in again.")

    if session.revoked_at is not None:
        # A revoked token being replayed suggests theft: drop every session
        # for that user and make them sign in again.
        await revoke_all_sessions(db, session.user_id)
        raise AuthError("Session revoked. Please sign in again.")

    if session.expires_at <= now:
        raise AuthError("Session expired. Please sign in again.")

    is_current = session.token_hash == token_hash
    if not is_current:
        # The token was already rotated. Inside the grace window this is a
        # race between two tabs; outside it, it is a replay.
        rotated_at = session.rotated_at
        within_grace = (
            rotated_at is not None and (now - rotated_at).total_seconds() <= REFRESH_GRACE_SECONDS
        )
        if not within_grace:
            await revoke_all_sessions(db, session.user_id)
            raise AuthError("Session replay detected. Please sign in again.")

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise AuthError("This account is disabled.", status_code=403)

    new_token = generate_token()
    if is_current:
        session.previous_token_hash = session.token_hash
    # A grace-window refresh leaves previous_token_hash alone, so the racing
    # tab's token stays valid for the rest of the window instead of being
    # knocked out by its own sibling.
    session.token_hash = hash_token(new_token)
    session.rotated_at = now
    session.last_used_at = now
    if ip_address:
        session.ip_address = ip_address
    await db.flush()
    return new_token, user


async def revoke_session(db: AsyncSession, token: str) -> None:
    """Revoke the session identified by a refresh token. Idempotent."""
    await db.execute(
        update(AuthSession)
        .where(AuthSession.token_hash == hash_token(token), AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def revoke_all_sessions(
    db: AsyncSession, user_id: uuid.UUID, *, except_session_id: uuid.UUID | None = None
) -> None:
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    if except_session_id is not None:
        stmt = stmt.where(AuthSession.id != except_session_id)
    await db.execute(stmt)


async def list_sessions(db: AsyncSession, user_id: uuid.UUID) -> list[AuthSession]:
    result = await db.execute(
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
        .order_by(AuthSession.last_used_at.desc())
    )
    return list(result.scalars().all())


def start_totp_enrolment(user: User) -> str:
    """Generate a pending TOTP secret. Not active until confirmed."""
    from quanta.core.security import generate_totp_secret

    secret = generate_totp_secret()
    user.totp_pending_secret = secret
    return secret


def confirm_totp_enrolment(user: User, code: str) -> list[str]:
    """Activate 2FA and return freshly generated recovery codes."""
    if not user.totp_pending_secret:
        raise AuthError("Start two-factor setup first.", status_code=400)

    if not verify_totp(user.totp_pending_secret, code):
        raise AuthError("That code is not valid. Check your authenticator app.", status_code=400)

    user.totp_secret = user.totp_pending_secret
    user.totp_pending_secret = None
    user.totp_enabled = True
    user.last_totp_counter = None

    codes = generate_recovery_codes()
    user.recovery_code_hashes = [hash_token(c) for c in codes]
    return codes
