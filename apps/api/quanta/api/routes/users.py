"""Current-user profile and preferences."""

from __future__ import annotations

from fastapi import APIRouter

from quanta.api.deps import CurrentUser, DbDep
from quanta.schemas.auth import PreferencesUpdate, UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def read_me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)


@router.patch("/me/preferences", response_model=UserResponse)
async def update_preferences(
    payload: PreferencesUpdate, user: CurrentUser, db: DbDep
) -> UserResponse:
    """Persist theme, locale, timezone and calendar choices."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)
