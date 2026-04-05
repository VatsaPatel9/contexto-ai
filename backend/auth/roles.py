"""Role and permission definitions for the AI Tutor RBAC system."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------
SUPER_ADMIN = "super_admin"
ADMIN = "admin"
USER = "user"

ALL_ROLES = [SUPER_ADMIN, ADMIN, USER]

# ---------------------------------------------------------------------------
# Permission definitions per role
# ---------------------------------------------------------------------------
PERMISSIONS: dict[str, list[str]] = {
    SUPER_ADMIN: [
        "chat",
        "upload_documents",
        "delete_documents",
        "manage_users",
        "manage_roles",
        "view_analytics",
        "grant_upload_permission",
        "manage_all",
    ],
    ADMIN: [
        "chat",
        "upload_documents",
        "delete_documents",
        "view_analytics",
        "grant_upload_permission",
    ],
    USER: [
        "chat",
        "view_own_history",
    ],
}

# Role assigned to users who are explicitly granted document upload permission
USER_UPLOADER = "user_uploader"
USER_UPLOADER_PERMISSIONS = ["chat", "view_own_history", "upload_documents"]


async def seed_roles() -> None:
    """Create all roles and attach their permissions (idempotent)."""
    from supertokens_python.recipe.userroles.asyncio import (
        create_new_role_or_add_permissions,
    )

    for role, perms in PERMISSIONS.items():
        await create_new_role_or_add_permissions(role, perms)

    # Special role for users granted upload permission
    await create_new_role_or_add_permissions(USER_UPLOADER, USER_UPLOADER_PERMISSIONS)
