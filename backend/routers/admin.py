"""Admin endpoints for user, role, permission, and moderation management."""

from __future__ import annotations

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


@router.get("/users/{user_id}/roles", response_model=UserRolesResponse)
async def get_user_roles_endpoint(
    user_id: str,
    session: SessionContainer = Depends(require_role(SUPER_ADMIN, ADMIN)),
):
    """Get all roles assigned to a user."""
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
    """View a user's profile: display name, email, uploads, tokens, and flag status."""
    profile = get_or_create_profile(db, user_id)
    db.commit()

    flag_svc = UserFlagService(db)
    flag = flag_svc.get_flag(user_id)

    roles_result = await get_roles_for_user("public", user_id)

    # Fetch email from SuperTokens
    email = None
    try:
        from supertokens_python.asyncio import get_user
        user = await get_user(user_id)
        if user:
            for lm in user.login_methods:
                if lm.email:
                    email = lm.email
                    break
    except Exception:
        pass

    return {
        "user_id": user_id,
        "display_name": profile.display_name,
        "email": email,
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
    """List all users with active violations (non-clean flag level)."""
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
    """Get detailed violation info for a specific user."""
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
    await _guard_super_admin_target(session, user_id)
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
    await _guard_super_admin_target(session, user_id)
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
