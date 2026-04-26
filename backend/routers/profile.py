"""User profile endpoint — lets authenticated users view and update their profile."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from supertokens_python.asyncio import delete_user, get_user
from supertokens_python.recipe.session import SessionContainer

from backend.auth.dependencies import require_auth
from backend.database import get_db
from backend.models.conversation import Conversation
from backend.models.dataset import Document
from backend.models.email_verification_attempt import EmailVerificationAttempt
from backend.models.password_reset_attempt import PasswordResetAttempt
from backend.models.user_course import UserCourse
from backend.models.user_flags import UserFlag, UserFlagService
from backend.models.user_profile import UserProfile, get_or_create_profile

logger = logging.getLogger(__name__)

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
            raise HTTPException(status_code=400, detail="Display name too long (max 100 chars)")
        profile.display_name = name if name else None

    db.commit()

    return {"result": "success", "display_name": profile.display_name}


@router.delete("/api/me")
async def delete_my_account(
    session: SessionContainer = Depends(require_auth()),
    db: DBSession = Depends(get_db),
):
    """Permanently delete the authenticated user's account and personal data.

    Irreversible. Removes:
      * The SuperTokens user record (email, password hash, role bindings).
      * The caller's private documents (and their pgvector segments via
        the cascade on `documents -> document_segments`).
      * Conversations and messages (cascade via the conversation FK).
      * Course enrollments, profile row, moderation flags, and rate-limit
        attempt history.

    Course-tagged and baseline-tagged documents the caller uploaded as
    admin / super_admin stay intact — they belong to the course or to
    the system, not to the individual leaving.

    Order of operations: tear down SuperTokens first so a partial
    failure can't leave a logged-in user with no local data. If
    SuperTokens succeeds and a local-cleanup query later raises, the
    orphan rows are unreachable (no user to log in as) — we log and
    move on rather than 500'ing the client.
    """
    user_id = session.get_user_id()

    try:
        await delete_user(user_id)
    except Exception as exc:
        logger.error("SuperTokens delete_user failed for %s: %s", user_id, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete account. Please try again.",
        )

    try:
        # Private uploads: cascade to document_segments via FK.
        db.query(Document).filter(
            Document.uploaded_by == user_id,
            Document.uploader_role == "private",
        ).delete(synchronize_session=False)

        # Conversations cascade-delete their messages.
        db.query(Conversation).filter(Conversation.user_id == user_id).delete(
            synchronize_session=False
        )

        db.query(UserCourse).filter(UserCourse.user_id == user_id).delete(
            synchronize_session=False
        )
        db.query(UserFlag).filter(UserFlag.user_id == user_id).delete(
            synchronize_session=False
        )
        db.query(UserProfile).filter(UserProfile.user_id == user_id).delete(
            synchronize_session=False
        )
        db.query(EmailVerificationAttempt).filter(
            EmailVerificationAttempt.user_id == user_id
        ).delete(synchronize_session=False)
        db.query(PasswordResetAttempt).filter(
            PasswordResetAttempt.user_id == user_id
        ).delete(synchronize_session=False)

        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(
            "Local cleanup partially failed for deleted user %s: %s", user_id, exc
        )

    try:
        await session.revoke_session()
    except Exception as exc:
        logger.warning("Session revoke failed after account delete: %s", exc)

    return {"result": "success"}
