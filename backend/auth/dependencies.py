"""FastAPI dependencies for SuperTokens session verification and RBAC."""

from __future__ import annotations

from supertokens_python.recipe.session import SessionContainer
from supertokens_python.recipe.session.framework.fastapi import verify_session
from supertokens_python.recipe.userroles import PermissionClaim, UserRoleClaim


def require_auth():
    """Dependency: any authenticated user with a valid session."""
    return verify_session()


def require_role(*roles: str):
    """Dependency: user must have at least one of the specified roles."""
    role_list = list(roles)
    return verify_session(
        override_global_claim_validators=lambda global_validators, session, user_context: [
            *global_validators,
            UserRoleClaim.validators.includes_any(role_list),
        ]
    )


def require_permission(permission: str):
    """Dependency: user must have the specified permission."""
    return verify_session(
        override_global_claim_validators=lambda global_validators, session, user_context: [
            *global_validators,
            PermissionClaim.validators.includes(permission),
        ]
    )


async def get_user_roles(session: SessionContainer) -> list[str]:
    """Extract roles from the current session's access token claims."""
    roles_claim = await session.get_claim_value(UserRoleClaim)
    return roles_claim if roles_claim else []
