"""Admin endpoints for user, role, permission, and moderation management."""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from supertokens_python.recipe.session import SessionContainer
from supertokens_python.recipe.userroles.asyncio import (
    add_role_to_user,
    get_roles_for_user,
    get_users_that_have_role,
    remove_user_role,
)
from supertokens_python.recipe.userroles.interfaces import (
    UnknownRoleError,
)

logger = logging.getLogger(__name__)

# Prefix used to mark a user as soft-deleted by rewriting their SuperTokens
# email to "delete-<unix_ts>-<original_email>". The original email becomes
# free for fresh sign-up, while the renamed account (and all its rows) is
# retained for the 30-day grace window before a janitor purges it.
DELETED_EMAIL_PREFIX = "delete-"

from backend.auth.dependencies import require_role
from backend.auth.roles import ADMIN, ALL_ROLES, SUPER_ADMIN, USER_UPLOADER
from backend.database import get_db
from backend.models.user_flags import FlagLevel, UserFlagService
from backend.models.user_profile import UserProfile, get_or_create_profile

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RoleAssignRequest(BaseModel):
    role: str


class UserRolesResponse(BaseModel):
    user_id: str
    roles: list[str]


class UploadLimitRequest(BaseModel):
    limit: int  # max number of documents the user can upload


class TokenLimitRequest(BaseModel):
    limit: Optional[int] = None  # None = unlimited


class BanRequest(BaseModel):
    reason: str = "Banned by admin"


# ═══════════════════════════════════════════════════════════════════════════
# ROLE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/users")
async def list_users(
    role: str | None = None,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
):
    """List users, optionally filtered by role.

    Admins cannot see super_admin users. Only super_admins can see other super_admins.
    """
    from backend.auth.dependencies import get_user_roles as _get_caller_roles
    caller_roles = await _get_caller_roles(session)
    is_super_admin = SUPER_ADMIN in caller_roles

    # Get super_admin user IDs so we can filter them out for non-super_admins
    hidden_user_ids: set[str] = set()
    if not is_super_admin:
        sa_result = await get_users_that_have_role("public", SUPER_ADMIN)
        if not isinstance(sa_result, UnknownRoleError):
            hidden_user_ids = set(sa_result.users)

    if role:
        # Don't let admins query the super_admin role directly
        if role == SUPER_ADMIN and not is_super_admin:
            return {"users": []}
        result = await get_users_that_have_role("public", role)
        if isinstance(result, UnknownRoleError):
            raise HTTPException(status_code=400, detail=f"Unknown role: {role}")
        filtered = [u for u in result.users if u not in hidden_user_ids]
        return {"users": filtered}

    roles_to_list = ALL_ROLES + [USER_UPLOADER]
    if not is_super_admin:
        roles_to_list = [r for r in roles_to_list if r != SUPER_ADMIN]

    all_users: dict[str, list[str]] = {}
    for r in roles_to_list:
        result = await get_users_that_have_role("public", r)
        if not isinstance(result, UnknownRoleError):
            filtered = [u for u in result.users if u not in hidden_user_ids]
            if filtered:
                all_users[r] = filtered
    return {"users_by_role": all_users}


async def _guard_super_admin_target(session: SessionContainer, target_user_id: str):
    """Raise 403 if a non-super_admin tries to access a super_admin user."""
    from backend.auth.dependencies import get_user_roles as _get_roles
    caller_roles = await _get_roles(session)
    if SUPER_ADMIN not in caller_roles:
        target_roles = await get_roles_for_user("public", target_user_id)
        if SUPER_ADMIN in target_roles.roles:
            raise HTTPException(status_code=403, detail="Access denied")


async def _admin_scope_user_ids(db: DBSession, caller_id: str) -> set[str]:
    """Return the set of user_ids enrolled in courses *caller_id* created.

    Used to scope an admin's user-management actions to only their own
    course members.
    """
    from backend.models.dataset import Dataset
    from backend.models.user_course import UserCourse

    rows = (
        db.query(UserCourse.user_id)
        .join(Dataset, Dataset.id == UserCourse.dataset_id)
        .filter(Dataset.created_by == caller_id)
        .all()
    )
    return {r[0] for r in rows}


async def _assert_can_manage_user(
    session: SessionContainer,
    target_user_id: str,
    db: DBSession,
) -> None:
    """Authorize the calling admin to manage *target_user_id*.

    * super_admin: always allowed (god-mode).
    * admin: target must be (a) NOT another admin or super_admin, and
      (b) enrolled in at least one course the caller created.
    * anyone else: 403.
    """
    from backend.auth.dependencies import get_user_roles as _roles

    caller_id = session.get_user_id()
    caller_roles = await _roles(session)

    if SUPER_ADMIN in caller_roles:
        return

    if ADMIN not in caller_roles:
        raise HTTPException(status_code=403, detail="Admin role required")

    # Self-management belongs on the profile page, not the admin panel.
    if target_user_id == caller_id:
        raise HTTPException(
            status_code=403,
            detail="Use the profile page to manage your own account.",
        )

    # Block admins from operating on other admins / super_admins.
    target_roles_result = await get_roles_for_user("public", target_user_id)
    target_roles = target_roles_result.roles
    if SUPER_ADMIN in target_roles or ADMIN in target_roles:
        raise HTTPException(status_code=403, detail="Cannot manage another admin")

    scope = await _admin_scope_user_ids(db, caller_id)
    if target_user_id not in scope:
        raise HTTPException(
            status_code=403,
            detail="You can only manage users enrolled in courses you created.",
        )


@router.get("/users/{user_id}/roles", response_model=UserRolesResponse)
async def get_user_roles_endpoint(
    user_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
):
    """Get all roles assigned to a user.

    Read-only: any admin may view any non-super_admin's roles. Scope only
    applies to mutating actions (ban, set-limits).
    """
    await _guard_super_admin_target(session, user_id)
    result = await get_roles_for_user("public", user_id)
    return UserRolesResponse(user_id=user_id, roles=result.roles)


@router.post("/users/{user_id}/role")
async def assign_role(
    user_id: str,
    body: RoleAssignRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN)),
):
    """Assign a role to a user. Only super_admin can assign roles."""
    result = await add_role_to_user("public", user_id, body.role)
    if isinstance(result, UnknownRoleError):
        raise HTTPException(status_code=400, detail=f"Unknown role: {body.role}")
    return {
        "result": "success",
        "user_id": user_id,
        "role": body.role,
        "did_user_already_have_role": result.did_user_already_have_role,
    }


@router.delete("/users/{user_id}/role")
async def remove_role(
    user_id: str,
    body: RoleAssignRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN)),
):
    """Remove a role from a user. Only super_admin can remove roles."""
    result = await remove_user_role("public", user_id, body.role)
    if isinstance(result, UnknownRoleError):
        raise HTTPException(status_code=400, detail=f"Unknown role: {body.role}")
    return {
        "result": "success",
        "user_id": user_id,
        "role": body.role,
        "did_user_have_role": result.did_user_have_role,
    }


# ═══════════════════════════════════════════════════════════════════════════
# USER PROFILE (upload limits, token usage, flag status)
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/users/{user_id}/profile")
async def get_user_profile(
    user_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    await _guard_super_admin_target(session, user_id)
    """View a user's profile: display name, email, uploads, tokens, and flag status.

    Read-only: any admin may view any non-super_admin's profile. The
    user-search dropdown caches display names/emails from this endpoint,
    so it must work for every visible user. Scope only applies to
    mutating actions further down.
    """
    profile = get_or_create_profile(db, user_id)
    db.commit()

    flag_svc = UserFlagService(db)
    flag = flag_svc.get_flag(user_id)

    roles_result = await get_roles_for_user("public", user_id)

    # Fetch email + verification status from SuperTokens. The recipe
    # user id we capture here lets the UI decide whether to show the
    # super_admin "Mark email verified" override button.
    email = None
    email_verified = False
    try:
        from supertokens_python.asyncio import get_user
        from supertokens_python.recipe.emailverification.asyncio import is_email_verified

        user = await get_user(user_id)
        if user:
            for lm in user.login_methods:
                if lm.email:
                    email = lm.email
                    try:
                        email_verified = await is_email_verified(lm.recipe_user_id, lm.email)
                    except Exception:
                        email_verified = False
                    break
    except Exception:
        pass

    return {
        "user_id": user_id,
        "display_name": profile.display_name,
        "email": email,
        "email_verified": email_verified,
        "roles": roles_result.roles,
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
            "last_offense_at": flag.last_offense_at.isoformat() if flag.last_offense_at else None,
            "restricted_until": flag.restricted_until.isoformat() if flag.restricted_until else None,
            "notes": flag.notes,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# UPLOAD LIMIT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/users/{user_id}/upload-limit")
async def set_upload_limit(
    user_id: str,
    body: UploadLimitRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Set or update a user's document upload limit.

    Also grants the ``user_uploader`` role if not already assigned.
    """
    await _assert_can_manage_user(session, user_id, db)
    if body.limit < 0:
        raise HTTPException(status_code=400, detail="Limit must be >= 0")

    profile = get_or_create_profile(db, user_id)
    profile.upload_limit = body.limit
    db.commit()

    # Ensure the user has the uploader role
    role_result = await add_role_to_user("public", user_id, USER_UPLOADER)

    return {
        "result": "success",
        "user_id": user_id,
        "upload_limit": profile.upload_limit,
        "upload_count": profile.upload_count,
        "role_granted": not role_result.did_user_already_have_role
        if not isinstance(role_result, UnknownRoleError) else False,
    }


@router.delete("/users/{user_id}/upload-limit")
async def revoke_upload_limit(
    user_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Revoke a user's upload permission and clear their limit."""
    await _assert_can_manage_user(session, user_id, db)
    profile = get_or_create_profile(db, user_id)
    profile.upload_limit = None
    db.commit()

    role_result = await remove_user_role("public", user_id, USER_UPLOADER)

    return {
        "result": "success",
        "user_id": user_id,
        "role_removed": role_result.did_user_have_role
        if not isinstance(role_result, UnknownRoleError) else False,
    }


# ═══════════════════════════════════════════════════════════════════════════
# TOKEN LIMIT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

@router.put("/users/{user_id}/token-limit")
async def set_token_limit(
    user_id: str,
    body: TokenLimitRequest,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Set or update a user's token budget. Send ``null`` for unlimited."""
    await _assert_can_manage_user(session, user_id, db)
    if body.limit is not None and body.limit < 0:
        raise HTTPException(status_code=400, detail="Token limit must be >= 0 or null")

    profile = get_or_create_profile(db, user_id)
    profile.token_limit = body.limit
    db.commit()

    return {
        "result": "success",
        "user_id": user_id,
        "token_limit": profile.token_limit,
        "tokens_used": profile.tokens_in + profile.tokens_out,
    }


# ═══════════════════════════════════════════════════════════════════════════
# VIOLATIONS & MODERATION
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/violations")
async def list_violations(
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """List all users with active violations (read-only)."""
    flag_svc = UserFlagService(db)
    flagged = flag_svc.get_flagged_users()

    return {
        "violations": [
            {
                "user_id": f.user_id,
                "flag_level": f.flag_level,
                "offense_count_mild": f.offense_count_mild,
                "offense_count_severe": f.offense_count_severe,
                "last_offense_at": f.last_offense_at.isoformat() if f.last_offense_at else None,
                "restricted_until": f.restricted_until.isoformat() if f.restricted_until else None,
                "notes": f.notes,
            }
            for f in flagged
        ],
        "total": len(flagged),
    }


@router.get("/users/{user_id}/violations")
async def get_user_violations(
    user_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    await _guard_super_admin_target(session, user_id)
    """Get detailed violation info for a specific user (read-only)."""
    flag_svc = UserFlagService(db)
    flag = flag_svc.get_flag(user_id)

    return {
        "user_id": user_id,
        "flag_level": flag.flag_level,
        "offense_count_mild": flag.offense_count_mild,
        "offense_count_severe": flag.offense_count_severe,
        "last_offense_at": flag.last_offense_at.isoformat() if flag.last_offense_at else None,
        "restricted_until": flag.restricted_until.isoformat() if flag.restricted_until else None,
        "notes": flag.notes,
    }


@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: str,
    body: BanRequest = BanRequest(),
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Ban (suspend) a user. They will be unable to send messages."""
    await _assert_can_manage_user(session, user_id, db)
    admin_id = session.get_user_id()
    flag_svc = UserFlagService(db)
    flag = flag_svc.admin_override(
        user_id=user_id,
        new_level=FlagLevel.SUSPENDED.value,
        admin_id=admin_id,
        reason=body.reason,
    )
    return {
        "result": "success",
        "user_id": user_id,
        "flag_level": flag.flag_level,
        "banned_by": admin_id,
    }


@router.post("/users/{user_id}/unban")
async def unban_user(
    user_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
    db: DBSession = Depends(get_db),
):
    """Unban a user by resetting their flag level to clean."""
    await _assert_can_manage_user(session, user_id, db)
    admin_id = session.get_user_id()
    flag_svc = UserFlagService(db)
    flag = flag_svc.admin_override(
        user_id=user_id,
        new_level=FlagLevel.CLEAN.value,
        admin_id=admin_id,
        reason="Unbanned by admin",
    )
    return {
        "result": "success",
        "user_id": user_id,
        "flag_level": flag.flag_level,
        "unbanned_by": admin_id,
    }


# ═══════════════════════════════════════════════════════════════════════════
# EMAIL VERIFICATION (super_admin override)
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/users/{user_id}/verify-email")
async def admin_verify_email(
    user_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN)),
):
    """Force-mark a user's email as verified.

    For support cases: a student says they verified but never see "OK"
    on the link page (email client mangled the URL, network blip,
    expired token, etc.). super_admin can bypass the token flow.
    Restricted to super_admin because this is an authentication override.
    """
    from supertokens_python.asyncio import get_user
    from supertokens_python.recipe.emailverification.asyncio import (
        create_email_verification_token,
        is_email_verified,
        verify_email_using_token,
    )
    from supertokens_python.recipe.emailverification.interfaces import (
        CreateEmailVerificationTokenOkResult,
        VerifyEmailUsingTokenOkResult,
    )

    user = await get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Pick the emailpassword login method (the only kind we support).
    target_email: str | None = None
    target_recipe_user_id = None
    for lm in user.login_methods:
        if lm.recipe_id == "emailpassword" and lm.email:
            target_email = lm.email
            target_recipe_user_id = lm.recipe_user_id
            break
    if target_email is None or target_recipe_user_id is None:
        raise HTTPException(status_code=400, detail="User has no email login method")

    # Fast path: already verified.
    already = await is_email_verified(target_recipe_user_id, target_email)
    if already:
        return {"result": "success", "user_id": user_id, "already_verified": True}

    # SuperTokens has no direct "set verified=true" API; the supported
    # path is create-then-consume a token in one round-trip on the server.
    token_result = await create_email_verification_token(
        "public", target_recipe_user_id, target_email
    )
    if not isinstance(token_result, CreateEmailVerificationTokenOkResult):
        # EmailAlreadyVerifiedError can race with the fast path above.
        return {"result": "success", "user_id": user_id, "already_verified": True}

    consume_result = await verify_email_using_token("public", token_result.token)
    if not isinstance(consume_result, VerifyEmailUsingTokenOkResult):
        raise HTTPException(status_code=500, detail="Verification failed unexpectedly")

    return {
        "result": "success",
        "user_id": user_id,
        "already_verified": False,
        "performed_by": session.get_user_id(),
    }


# ═══════════════════════════════════════════════════════════════════════════
# SOFT DELETE (super_admin only)
# ═══════════════════════════════════════════════════════════════════════════

@router.delete("/users/{user_id}")
async def soft_delete_user(
    user_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN)),
):
    """Soft-delete a user by renaming their email and revoking sessions.

    The SuperTokens email is rewritten to ``delete-<unix_ts>-<original>``
    so the original address is immediately free for a fresh sign-up,
    while the renamed account and every row keyed off ``user_id``
    (profile, conversations, documents, enrollments, flags) is retained
    for a 30-day grace window. A separate janitor purges those rows
    once the prefix timestamp is older than 30 days.

    Restricted to super_admin. Guards:
      * cannot delete yourself (use ``DELETE /api/me`` instead).
      * cannot delete another super_admin (mutual-protection).
      * cannot delete an already-soft-deleted user (idempotent reject).
    """
    from supertokens_python.asyncio import get_user
    from supertokens_python.recipe.emailpassword.asyncio import (
        update_email_or_password,
    )
    from supertokens_python.recipe.emailpassword.interfaces import (
        EmailAlreadyExistsError,
        UnknownUserIdError,
        UpdateEmailOrPasswordEmailChangeNotAllowedError,
    )
    from supertokens_python.recipe.session.asyncio import (
        revoke_all_sessions_for_user,
    )

    caller_id = session.get_user_id()
    if user_id == caller_id:
        raise HTTPException(
            status_code=400,
            detail="Use the profile page to delete your own account.",
        )

    target_roles_result = await get_roles_for_user("public", user_id)
    if SUPER_ADMIN in target_roles_result.roles:
        raise HTTPException(
            status_code=403,
            detail="Cannot delete another super_admin.",
        )

    user = await get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    target_email: str | None = None
    target_recipe_user_id = None
    for lm in user.login_methods:
        if lm.recipe_id == "emailpassword" and lm.email:
            target_email = lm.email
            target_recipe_user_id = lm.recipe_user_id
            break
    if target_email is None or target_recipe_user_id is None:
        raise HTTPException(
            status_code=400,
            detail="User has no email login method to rename.",
        )

    if target_email.startswith(DELETED_EMAIL_PREFIX):
        raise HTTPException(
            status_code=409,
            detail="User is already soft-deleted.",
        )

    deleted_at = int(time.time())
    new_email = f"{DELETED_EMAIL_PREFIX}{deleted_at}-{target_email}"

    update_result = await update_email_or_password(
        target_recipe_user_id, email=new_email
    )
    if isinstance(update_result, EmailAlreadyExistsError):
        # The freed-up slot we're trying to write into is taken — extremely
        # unlikely (timestamp collision on the same original email) but
        # surface it instead of silently swallowing.
        raise HTTPException(
            status_code=409,
            detail="Renamed email collision — try again.",
        )
    if isinstance(update_result, UnknownUserIdError):
        raise HTTPException(status_code=404, detail="User not found")
    if isinstance(update_result, UpdateEmailOrPasswordEmailChangeNotAllowedError):
        raise HTTPException(
            status_code=400,
            detail=getattr(update_result, "reason", "Email change not allowed"),
        )

    try:
        await revoke_all_sessions_for_user(user_id)
    except Exception as exc:
        # Email is already renamed at this point, so the user can no longer
        # authenticate even if a session sticks around briefly. Log and move on.
        logger.warning(
            "Session revoke failed for soft-deleted user %s: %s", user_id, exc
        )

    return {
        "result": "success",
        "user_id": user_id,
        "original_email": target_email,
        "new_email": new_email,
        "deleted_at": deleted_at,
        "performed_by": caller_id,
    }
