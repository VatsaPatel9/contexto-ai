"""User profile endpoint — lets authenticated users view and update their profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from supertokens_python.asyncio import get_user
from supertokens_python.recipe.session import SessionContainer

from backend.auth.dependencies import require_auth
from backend.database import get_db
from backend.models.user_flags import UserFlagService
from backend.models.user_profile import get_or_create_profile

router = APIRouter(tags=["profile"])


async def _get_email(user_id: str) -> str | None:
    """Fetch the user's email from SuperTokens core."""
    try:
        user = await get_user(user_id)
        if user is None:
            return None
        # SuperTokens User object has login_methods, each with an email
        for lm in user.login_methods:
            if lm.email:
                return lm.email
        return None
    except Exception:
        return None


@router.get("/api/me")
async def get_my_profile(
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Return the authenticated user's own profile stats, display name, and email."""
    user_id = session.get_user_id()

    profile = get_or_create_profile(db, user_id)
    db.commit()

    flag_svc = UserFlagService(db)
    flag = flag_svc.get_flag(user_id)

    email = await _get_email(user_id)

    return {
        "user_id": user_id,
        "display_name": profile.display_name,
        "email": email,
        "uploads": {
            "count": profile.upload_count,
            "limit": profile.upload_limit,
        },
        "tokens": {
            "in": profile.tokens_in,
            "out": profile.tokens_out,
            "total": profile.tokens_in + profile.tokens_out,
            "limit": profile.token_limit,
        },
        "flags": {
            "level": flag.flag_level,
            "offense_count_mild": flag.offense_count_mild,
            "offense_count_severe": flag.offense_count_severe,
        },
    }


class UpdateProfileRequest(BaseModel):
    display_name: str | None = None


@router.put("/api/me")
async def update_my_profile(
    body: UpdateProfileRequest,
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Update the authenticated user's display name."""
    user_id = session.get_user_id()
    profile = get_or_create_profile(db, user_id)

    if body.display_name is not None:
        name = body.display_name.strip()
        if len(name) > 100:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Display name too long (max 100 chars)")
        profile.display_name = name if name else None

    db.commit()

    return {"result": "success", "display_name": profile.display_name}
