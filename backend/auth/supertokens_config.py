"""SuperTokens initialization for the AI Tutor backend."""

from __future__ import annotations

import logging

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

logger = logging.getLogger(__name__)

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
        """Split into three DB-touching phases so we don't hold a pool
        connection across the SuperTokens Core round-trip (~100-500 ms).

        Phase 1: rate-limit lookup (~ms, then close)
        Phase 2: Core call (no DB held)
        Phase 3: record successful attempt (~ms, then close)

        The rate-limit race window between Phase 1 and Phase 3 is the same
        size as it was before (the previous version also did the Core
        round-trip with the DB connection open but never re-checked the
        count after it returned), so behavior is preserved.
        """
        from datetime import datetime, timedelta, timezone
        from backend.database import SessionLocal
        from backend.models.email_verification_attempt import EmailVerificationAttempt

        user_id = session.get_user_id()
        window_start = datetime.now(timezone.utc) - timedelta(hours=RESEND_WINDOW_HOURS)

        # Phase 1: rate-limit check.
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
        finally:
            db.close()

        # Phase 2: Core call. No DB connection held — frees the slot for
        # other requests waiting on the pool.
        result = await original_generate_token_post(session, api_options, user_context)

        # Phase 3: record the attempt only if the Core call succeeded.
        if getattr(result, "status", None) == "OK":
            db = SessionLocal()
            try:
                db.add(EmailVerificationAttempt(user_id=user_id))
                db.commit()
            finally:
                db.close()

        return result

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


def _is_exempt_domain(settings: Settings, email: str) -> bool:
    """Whether `email`'s domain is in VERIFICATION_EXEMPT_DOMAINS."""
    if "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1].lower()
    exempt = [
        d.strip().lstrip("@").lower()
        for d in (settings.verification_exempt_domains or "").split(",")
        if d.strip()
    ]
    return bool(domain) and domain in exempt


async def _force_verify_only(tenant_id, recipe_user_id, email) -> None:
    """Mark `email` verified in the SuperTokens Core. Idempotent —
    returns immediately if the user is already verified.

    SuperTokens has no direct ``set verified = true`` API; the supported
    pattern is create-then-consume a token in one server-side round-trip
    (the admin "Mark verified" endpoint does the same).

    This helper does NOT touch the caller's session. Use it on sign-in
    paths where the session was minted at the same moment as the verify
    state and its st-ev claim is already correct.
    """
    from supertokens_python.recipe.emailverification.asyncio import (
        create_email_verification_token,
        is_email_verified,
        verify_email_using_token,
    )
    from supertokens_python.recipe.emailverification.interfaces import (
        CreateEmailVerificationTokenOkResult,
    )

    if await is_email_verified(recipe_user_id, email):
        return

    tok = await create_email_verification_token(tenant_id, recipe_user_id, email)
    if isinstance(tok, CreateEmailVerificationTokenOkResult):
        await verify_email_using_token(tenant_id, tok.token)


async def _refresh_session_verified_claim(session) -> None:
    """Pull the current verified state from Core into `session`'s
    access-token payload.

    Only needed on sign-up: the session is minted with st-ev=false
    (the user wasn't verified at session-creation time), and we then
    flip the Core state to verified afterwards. Without this refresh,
    the access token would keep st-ev=false until the claim's
    refetch TTL elapsed and the user's first /api/me would 403.

    Do NOT call this on sign-in — the SuperTokens SDK stamps the
    correct st-ev value into the access token via the EmailVerification
    recipe's session-lifecycle hook when the session is created, so an
    extra round-trip to Core's regenerate_access_token endpoint is
    redundant and (empirically) the trigger for 502s on the success
    path of exempt-domain sign-ins.
    """
    if session is None:
        return
    from supertokens_python.recipe.emailverification import (
        EmailVerificationClaim,
    )
    await session.fetch_and_set_claim(EmailVerificationClaim)


def _override_emailpassword_apis(settings: Settings, original: EmailPasswordAPIInterface):
    """Override signup to optionally gate email domain and capture display_name,
    rate-limit the forgot-password endpoint the same way email verification
    resends are rate-limited, and on sign-in clear the unverified state for
    accounts whose domain is in VERIFICATION_EXEMPT_DOMAINS (covers users
    who signed up before the domain was added to the exempt list)."""

    original_sign_up_post = original.sign_up_post
    original_sign_in_post = original.sign_in_post
    original_generate_reset_token_post = original.generate_password_reset_token_post

    async def generate_password_reset_token_post(
        form_fields: list[FormField],
        tenant_id: str,
        api_options: EmailPasswordAPIOptions = None,
        user_context=None,
    ):
        """Rate-limit to RESEND_MAX_ATTEMPTS per RESEND_WINDOW_HOURS per user.

        The endpoint is unauthenticated so we can't key on session. Instead
        we look the email up against EmailPassword users and key on the
        resolved user_id. Unknown emails fall through to the SDK, which
        returns OK regardless — that's SuperTokens' built-in defense
        against email enumeration and we preserve it.
        """
        from datetime import datetime, timedelta, timezone
        from supertokens_python.asyncio import list_users_by_account_info
        from supertokens_python.types.base import AccountInfoInput
        from backend.database import SessionLocal
        from backend.models.password_reset_attempt import PasswordResetAttempt

        email = ""
        for field in form_fields:
            if field.id == "email":
                email = field.value.strip().lower()

        user_id: str | None = None
        if email:
            try:
                users = await list_users_by_account_info(
                    tenant_id, AccountInfoInput(email=email)
                )
                for u in users:
                    for lm in u.login_methods:
                        if lm.recipe_id == "emailpassword" and lm.has_same_email_as(email):
                            user_id = u.id
                            break
                    if user_id:
                        break
            except Exception:
                # Lookup failure shouldn't block the reset flow —
                # fall through and let SuperTokens handle it.
                user_id = None

        if user_id is None:
            # Unknown email → let the SDK return its enumeration-safe OK.
            return await original_generate_reset_token_post(
                form_fields, tenant_id, api_options, user_context
            )

        # Three-phase to keep the DB connection out of the SuperTokens
        # Core round-trip. See generate_email_verify_token_post for the
        # rationale and race-window note.
        window_start = datetime.now(timezone.utc) - timedelta(hours=RESEND_WINDOW_HOURS)

        # Phase 1: rate-limit check.
        db = SessionLocal()
        try:
            recent = (
                db.query(PasswordResetAttempt)
                .filter(
                    PasswordResetAttempt.user_id == user_id,
                    PasswordResetAttempt.created_at >= window_start,
                )
                .count()
            )
            if recent >= RESEND_MAX_ATTEMPTS:
                return GeneralErrorResponse(
                    message=(
                        f"You've requested {RESEND_MAX_ATTEMPTS} password-reset "
                        f"emails in the last {RESEND_WINDOW_HOURS} hours. "
                        "Please wait before requesting another."
                    )
                )
        finally:
            db.close()

        # Phase 2: Core call with no DB held.
        result = await original_generate_reset_token_post(
            form_fields, tenant_id, api_options, user_context
        )

        # Phase 3: record the attempt only if the Core call succeeded.
        if getattr(result, "status", None) == "OK":
            db = SessionLocal()
            try:
                db.add(PasswordResetAttempt(user_id=user_id))
                db.commit()
            finally:
                db.close()

        return result

    async def sign_up_post(
        form_fields: list[FormField],
        tenant_id: str,
        session=None,
        should_try_linking_with_session_user=None,
        api_options: EmailPasswordAPIOptions = None,
        user_context=None,
    ):
        from backend.services.terms import CURRENT_TERMS_VERSION

        email = ""
        display_name = ""
        terms_accepted_value = ""
        terms_version_value = ""
        for field in form_fields:
            if field.id == "email":
                email = field.value.strip().lower()
            elif field.id == "display_name":
                display_name = field.value.strip()
            elif field.id == "terms_accepted":
                terms_accepted_value = (field.value or "").strip().lower()
            elif field.id == "terms_version":
                terms_version_value = (field.value or "").strip()

        # Server-side gate: signup is rejected unless the request carries
        # an affirmative acceptance of the *current* Terms/Privacy version.
        # Anyone who skips the UI checkbox (XSS, raw curl, etc.) lands
        # here with terms_accepted != "true" and is bounced.
        if terms_accepted_value != "true" or terms_version_value != CURRENT_TERMS_VERSION:
            from supertokens_python.recipe.emailpassword.interfaces import (
                SignUpPostNotAllowedResponse,
            )
            return SignUpPostNotAllowedResponse(
                reason="You must accept the Terms of Service and Privacy Policy to create an account."
            )

        # Email-domain gate. Controlled by RESTRICT_EMAIL_DOMAIN env var
        # (default True). ALLOWED_EMAIL_DOMAIN is a comma-separated list
        # of permitted domains — e.g. "psu.edu,sainttheresaschool.org".
        if settings.restrict_email_domain:
            allowed_domains = [
                d.strip().lstrip("@").lower()
                for d in settings.allowed_email_domain.split(",")
                if d.strip()
            ]
            if allowed_domains and not any(
                email.endswith(f"@{d}") for d in allowed_domains
            ):
                from supertokens_python.recipe.emailpassword.interfaces import (
                    SignUpPostNotAllowedResponse,
                )
                pretty = ", ".join(f"@{d}" for d in allowed_domains)
                return SignUpPostNotAllowedResponse(
                    reason=f"Only {pretty} email addresses are allowed."
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

            # Save display_name + Terms acceptance to UserProfile.
            # The acceptance row is the audit trail; we already gated the
            # request above, so reaching this branch means the user
            # affirmatively agreed to ``CURRENT_TERMS_VERSION``.
            try:
                from datetime import datetime, timezone
                from backend.database import SessionLocal
                from backend.models.user_profile import get_or_create_profile
                db = SessionLocal()
                try:
                    profile = get_or_create_profile(db, result.user.id)
                    if display_name:
                        profile.display_name = display_name
                    profile.terms_version = CURRENT_TERMS_VERSION
                    profile.terms_accepted_at = datetime.now(timezone.utc)
                    db.commit()
                finally:
                    db.close()
            except Exception:
                pass  # Non-fatal — user can re-confirm later from the profile flow

            # Either auto-verify (exempt domain) or fire the usual
            # verification link. Exempt domains exist for orgs whose
            # mail server rejects our SMTP — the link would bounce
            # and the user would be locked out forever. Errors are
            # swallowed so SMTP/Core blips can't fail the signup; the
            # user can hit Resend (or an admin can use Mark verified)
            # from the /auth/check-email page.
            try:
                recipe_user_id = result.user.login_methods[0].recipe_user_id
                if _is_exempt_domain(settings, email):
                    # Exempt domain: flip the Core verify state, then
                    # refresh the just-minted session so its st-ev
                    # claim reflects the new state instead of the
                    # false it was stamped with at creation time.
                    await _force_verify_only(tenant_id, recipe_user_id, email)
                    await _refresh_session_verified_claim(result.session)
                else:
                    from supertokens_python.recipe.emailverification.asyncio import (
                        send_email_verification_email,
                    )
                    await send_email_verification_email(
                        tenant_id,
                        result.user.id,
                        recipe_user_id,
                        email,
                    )
            except Exception:
                # The user account is created (the SDK already committed
                # it); we don't want a Core/SMTP blip to surface as a
                # 5xx to the client. But we DO want the trace in Railway
                # logs so the next failure isn't invisible the way the
                # exempt-domain 502 was. Logged with full stack frame.
                logger.exception(
                    "Post-signup verify/email step failed for %s (exempt=%s)",
                    email,
                    _is_exempt_domain(settings, email),
                )

        return result

    async def sign_in_post(
        form_fields: list[FormField],
        tenant_id: str,
        session=None,
        should_try_linking_with_session_user=None,
        api_options: EmailPasswordAPIOptions = None,
        user_context=None,
    ):
        """On a successful sign-in from an exempt domain, clear any
        lingering unverified state so the user lands straight in the
        app instead of being shipped to /auth/check-email.

        Covers the back-fill case: anyone who tried to sign up before
        their domain was added to ``VERIFICATION_EXEMPT_DOMAINS`` is
        sitting in the DB with the verified flag off. _force_verify_only
        is idempotent, so on the common case (user already verified)
        it's a single cheap Core round-trip that returns immediately.
        """
        from supertokens_python.recipe.emailpassword.interfaces import (
            SignInPostOkResult,
        )

        result = await original_sign_in_post(
            form_fields=form_fields,
            tenant_id=tenant_id,
            session=session,
            should_try_linking_with_session_user=should_try_linking_with_session_user,
            api_options=api_options,
            user_context=user_context,
        )

        if isinstance(result, SignInPostOkResult):
            email = ""
            for field in form_fields:
                if field.id == "email":
                    email = field.value.strip().lower()
            if _is_exempt_domain(settings, email):
                try:
                    # Back-fill only: if this user signed up before the
                    # domain was added to VERIFICATION_EXEMPT_DOMAINS,
                    # _force_verify_only flips them to verified in Core.
                    # For users who are already verified (the common
                    # case), it's a cheap idempotent no-op (one Core
                    # round-trip that returns "already verified").
                    #
                    # We deliberately do NOT touch result.session here.
                    # The SuperTokens SDK has already stamped the
                    # correct st-ev value into the access token via the
                    # EmailVerification recipe's session-lifecycle hook
                    # at session-creation time. Calling
                    # session.fetch_and_set_claim here triggers an
                    # extra Core round-trip (regenerate_access_token)
                    # that was the trigger for 502s on this path.
                    recipe_user_id = result.user.login_methods[0].recipe_user_id
                    await _force_verify_only(tenant_id, recipe_user_id, email)
                except Exception:
                    # Sign-in itself already succeeded; a back-fill
                    # failure is not fatal — surface the trace so the
                    # next failure is debuggable in Railway logs.
                    logger.exception(
                        "Sign-in back-fill verify failed for exempt-domain user %s",
                        email,
                    )

        return result

    original.sign_up_post = sign_up_post
    original.sign_in_post = sign_in_post
    original.generate_password_reset_token_post = generate_password_reset_token_post
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
                    # Terms / Privacy acceptance is required at signup.
                    # The override above also re-validates these values
                    # so a client that drops the formField is rejected
                    # rather than silently passing through.
                    InputFormField(id="terms_accepted"),
                    InputFormField(id="terms_version"),
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
