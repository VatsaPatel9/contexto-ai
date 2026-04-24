"""SuperTokens initialization for the AI Tutor backend."""

from __future__ import annotations

from supertokens_python import InputAppInfo, SupertokensConfig, init
from supertokens_python.ingredients.emaildelivery.types import (
    EmailDeliveryConfig,
    SMTPSettings,
    SMTPSettingsFrom,
)
from supertokens_python.recipe import (
    dashboard,
    emailpassword,
    emailverification,
    session,
    userroles,
)
from supertokens_python.recipe.emailpassword.emaildelivery.services.smtp import (
    SMTPService as EmailPasswordSMTPService,
)
from supertokens_python.recipe.emailpassword.interfaces import (
    APIInterface as EmailPasswordAPIInterface,
    APIOptions as EmailPasswordAPIOptions,
    SignUpPostOkResult,
)
from supertokens_python.recipe.emailpassword.types import FormField, InputFormField
from supertokens_python.recipe.emailverification.emaildelivery.services.smtp import (
    SMTPService as EmailVerificationSMTPService,
)
from supertokens_python.types import GeneralErrorResponse

from backend.config import Settings

RESEND_WINDOW_HOURS = 24
RESEND_MAX_ATTEMPTS = 3


def _override_emailverification_apis(original):
    """Two tweaks on the emailverification endpoints:

    1. After a successful POST /auth/user/email/verify (the link-click
       endpoint), auto-create a session if the user doesn't already
       have one — so the "click email -> signed in" flow works even
       when they open the link in a fresh browser.

    2. Rate-limit POST /auth/user/email/verify/token (user-initiated
       resend) to RESEND_MAX_ATTEMPTS per RESEND_WINDOW_HOURS per user.

    Response types are checked by their .status attribute rather than
    imported classes — the class names move between supertokens-python
    releases and we'd rather not pin.
    """

    # Method on supertokens-python APIInterface is named `email_verify_post`
    # with signature (token, session, tenant_id, api_options, user_context).
    # Confirmed against the installed
    # supertokens_python/recipe/emailverification/interfaces.py.
    original_email_verify_post = original.email_verify_post
    original_generate_token_post = original.generate_email_verify_token_post

    async def email_verify_post(token, session, tenant_id, api_options, user_context):
        result = await original_email_verify_post(
            token, session, tenant_id, api_options, user_context
        )
        if getattr(result, "status", None) == "OK" and session is None:
            # Fresh browser (no signup-time session cookie): create one
            # so the frontend redirects into a signed-in state.
            try:
                from supertokens_python.recipe.session.asyncio import create_new_session
                user = getattr(result, "user", None)
                recipe_user_id = getattr(user, "recipe_user_id", None)
                if recipe_user_id is not None:
                    new_session = await create_new_session(
                        api_options.request,
                        tenant_id or "public",
                        recipe_user_id,
                    )
                    # Attach to the result so the SDK's response helper
                    # includes the session cookies on the outgoing response.
                    try:
                        result.new_session = new_session
                    except Exception:
                        pass
            except Exception:
                # Auto-login is a nice-to-have; failure must not
                # fail the verification.
                pass
        return result

    async def generate_email_verify_token_post(session, api_options, user_context):
        from datetime import datetime, timedelta, timezone
        from backend.database import SessionLocal
        from backend.models.email_verification_attempt import EmailVerificationAttempt

        user_id = session.get_user_id()
        window_start = datetime.now(timezone.utc) - timedelta(hours=RESEND_WINDOW_HOURS)

        db = SessionLocal()
        try:
            recent = (
                db.query(EmailVerificationAttempt)
                .filter(
                    EmailVerificationAttempt.user_id == user_id,
                    EmailVerificationAttempt.created_at >= window_start,
                )
                .count()
            )
            if recent >= RESEND_MAX_ATTEMPTS:
                return GeneralErrorResponse(
                    message=(
                        f"You've requested {RESEND_MAX_ATTEMPTS} verification "
                        f"emails in the last {RESEND_WINDOW_HOURS} hours. "
                        "Please wait before requesting another."
                    )
                )

            result = await original_generate_token_post(session, api_options, user_context)

            if getattr(result, "status", None) == "OK":
                db.add(EmailVerificationAttempt(user_id=user_id))
                db.commit()

            return result
        finally:
            db.close()

    original.email_verify_post = email_verify_post
    original.generate_email_verify_token_post = generate_email_verify_token_post
    return original


def _build_smtp_settings(settings: Settings) -> SMTPSettings | None:
    if not settings.smtp_username or not settings.smtp_password:
        return None
    return SMTPSettings(
        host=settings.smtp_host,
        port=settings.smtp_port,
        from_=SMTPSettingsFrom(
            name=settings.smtp_from_name,
            email=settings.smtp_from_email or settings.smtp_username,
        ),
        password=settings.smtp_password,
        secure=False,  # port 587 uses STARTTLS, not implicit TLS
    )


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
    """Initialise SuperTokens SDK with EmailPassword + Session + UserRoles + EmailVerification."""
    smtp_settings = _build_smtp_settings(settings)

    ep_email_delivery = (
        EmailDeliveryConfig(service=EmailPasswordSMTPService(smtp_settings=smtp_settings))
        if smtp_settings
        else None
    )
    ev_email_delivery = (
        EmailDeliveryConfig(service=EmailVerificationSMTPService(smtp_settings=smtp_settings))
        if smtp_settings
        else None
    )

    recipe_list = [
        emailpassword.init(
            sign_up_feature=emailpassword.InputSignUpFeature(
                form_fields=[
                    InputFormField(id="display_name", optional=True),
                ],
            ),
            override=emailpassword.InputOverrideConfig(
                apis=lambda orig: _override_emailpassword_apis(settings, orig),
            ),
            email_delivery=ep_email_delivery,
        ),
        session.init(),
        emailverification.init(
            mode="REQUIRED" if settings.email_verification_required else "OPTIONAL",
            email_delivery=ev_email_delivery,
            override=emailverification.InputOverrideConfig(
                apis=_override_emailverification_apis,
            ),
        ),
        userroles.init(),
        dashboard.init(),
    ]

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
        recipe_list=recipe_list,
    )
