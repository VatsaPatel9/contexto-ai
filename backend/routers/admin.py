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
    db: DBSession = Depends(get_db),
):
    """List users, optionally filtered by role.

    super_admin sees every user. admin sees only users enrolled in courses
    they created (and never any other admin / super_admin).
    """
    from backend.auth.dependencies import get_user_roles as _get_caller_roles
    caller_id = session.get_user_id()
    caller_roles = await _get_caller_roles(session)
    is_super_admin = SUPER_ADMIN in caller_roles

    # For non-super-admins, build the visibility scope:
    # - hidden: every super_admin and every admin (other admins are off-limits)
    # - allowed: users enrolled in courses the caller created
    hidden_user_ids: set[str] = set()
    allowed_user_ids: set[str] | None = None  # None = no scope filter (super_admin)
    if not is_super_admin:
        for hidden_role in (SUPER_ADMIN, ADMIN):
            r = await get_users_that_have_role("public", hidden_role)
            if not isinstance(r, UnknownRoleError):
                hidden_user_ids.update(r.users)
        # Always allow the caller themselves to remain visible? No — self-management
        # lives on the profile page; we already drop the caller from the dropdown.
        allowed_user_ids = await _admin_scope_user_ids(db, caller_id)

    def _in_scope(user_id: str) -> bool:
        if user_id in hidden_user_ids:
            return False
        if allowed_user_ids is None:
            return True
        return user_id in allowed_user_ids

    if role:
        # Admins cannot enumerate the super_admin or admin roles.
        if not is_super_admin and role in (SUPER_ADMIN, ADMIN):
            return {"users": []}
        result = await get_users_that_have_role("public", role)
        if isinstance(result, UnknownRoleError):
            raise HTTPException(status_code=400, detail=f"Unknown role: {role}")
        return {"users": [u for u in result.users if _in_scope(u)]}

    roles_to_list = ALL_ROLES + [USER_UPLOADER]
    if not is_super_admin:
        roles_to_list = [r for r in roles_to_list if r not in (SUPER_ADMIN, ADMIN)]

    all_users: dict[str, list[str]] = {}
    for r in roles_to_list:
        result = await get_users_that_have_role("public", r)
        if not isinstance(result, UnknownRoleError):
            filtered = [u for u in result.users if _in_scope(u)]
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
    db: DBSession = Depends(get_db),
):
    """Get all roles assigned to a user."""
    await _assert_can_manage_user(session, user_id, db)
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
    await _assert_can_manage_user(session, user_id, db)
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
    """List flagged users (super_admin: all; admin: only their course members)."""
    from backend.auth.dependencies import get_user_roles as _roles
    caller_roles = await _roles(session)
    flag_svc = UserFlagService(db)
    flagged = flag_svc.get_flagged_users()

    if SUPER_ADMIN not in caller_roles:
        caller_id = session.get_user_id()
        scope = await _admin_scope_user_ids(db, caller_id)
        flagged = [f for f in flagged if f.user_id in scope]

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
    await _assert_can_manage_user(session, user_id, db)
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
