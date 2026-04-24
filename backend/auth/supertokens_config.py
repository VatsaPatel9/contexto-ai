"""SuperTokens initialization for the AI Tutor backend."""

from __future__ import annotations

from supertokens_python import InputAppInfo, SupertokensConfig, init
from supertokens_python.recipe import dashboard, emailpassword, session, userroles
from supertokens_python.recipe.emailpassword.interfaces import (
    APIInterface as EmailPasswordAPIInterface,
    APIOptions as EmailPasswordAPIOptions,
    SignUpPostOkResult,
)
from supertokens_python.recipe.emailpassword.types import FormField, InputFormField

from backend.config import Settings


def _override_emailpassword_apis(settings: Settings, original: EmailPasswordAPIInterface):
    """Override signup to optionally gate email domain and capture display_name."""

    original_sign_up_post = original.sign_up_post

    async def sign_up_post(
        form_fields: list[FormField],
        tenant_id: str,
        session=None,
        should_try_linking_with_session_user=None,
        api_options: EmailPasswordAPIOptions = None,
        user_context=None,
    ):
        email = ""
        display_name = ""
        for field in form_fields:
            if field.id == "email":
                email = field.value.strip().lower()
            elif field.id == "display_name":
                display_name = field.value.strip()

        # Email-domain gate. Controlled by RESTRICT_EMAIL_DOMAIN env var
        # (default True). When enabled, only ALLOWED_EMAIL_DOMAIN passes.
        if settings.restrict_email_domain:
            allowed = settings.allowed_email_domain.strip().lstrip("@").lower()
            if allowed and not email.endswith(f"@{allowed}"):
                from supertokens_python.recipe.emailpassword.interfaces import (
                    SignUpPostNotAllowedResponse,
                )
                return SignUpPostNotAllowedResponse(
                    reason=f"Only @{allowed} email addresses are allowed."
                )

        result = await original_sign_up_post(
            form_fields=form_fields,
            tenant_id=tenant_id,
            session=session,
            should_try_linking_with_session_user=should_try_linking_with_session_user,
            api_options=api_options,
            user_context=user_context,
        )

        if isinstance(result, SignUpPostOkResult):
            # Auto-assign "user" role
            from supertokens_python.recipe.userroles.asyncio import add_role_to_user
            await add_role_to_user(tenant_id, result.user.id, "user")

            # Save display_name to UserProfile
            if display_name:
                try:
                    from backend.database import SessionLocal
                    from backend.models.user_profile import get_or_create_profile
                    db = SessionLocal()
                    try:
                        profile = get_or_create_profile(db, result.user.id)
                        profile.display_name = display_name
                        db.commit()
                    finally:
                        db.close()
                except Exception:
                    pass  # Non-fatal — user can set name later from profile

        return result

    original.sign_up_post = sign_up_post
    return original


def init_supertokens(settings: Settings) -> None:
    """Initialise SuperTokens SDK with EmailPassword + Session + UserRoles."""
    init(
        app_info=InputAppInfo(
            app_name="Contexto",
            api_domain=settings.auth_api_domain,
            website_domain=settings.auth_website_domain,
            api_base_path="/auth",
            website_base_path="/auth",
        ),
        supertokens_config=SupertokensConfig(
            connection_uri=settings.supertokens_connection_uri,
            api_key=settings.supertokens_api_key or None,
        ),
        framework="fastapi",
        recipe_list=[
            emailpassword.init(
                sign_up_feature=emailpassword.InputSignUpFeature(
                    form_fields=[
                        InputFormField(id="display_name", optional=True),
                    ],
                ),
                override=emailpassword.InputOverrideConfig(
                    apis=lambda orig: _override_emailpassword_apis(settings, orig),
                ),
            ),
            session.init(),
            userroles.init(),
            dashboard.init(),
        ],
    )
