"""Cross-device email verification endpoint.

The SuperTokens Web JS SDK can fail to consume a verification token when
the link is opened on a different device than the one that signed up
(no session, different cookies, browser restrictions). To make the link
work on *any* device, we expose a small backend endpoint that takes the
token from the URL and consumes it via the SuperTokens *Python* SDK,
which has no session requirement.

Single-use, short-lived (2h) tokens — same security model as the SDK
path. The endpoint is unauthenticated (the token *is* the auth) and
rate-limited per IP to prevent token-fishing.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from supertokens_python.recipe.emailverification.asyncio import (
    verify_email_using_token,
)
from supertokens_python.recipe.emailverification.interfaces import (
    VerifyEmailUsingTokenOkResult,
)

from backend.services.rate_limiter import Window, _check_windows

router = APIRouter()
logger = logging.getLogger(__name__)


class VerifyEmailTokenBody(BaseModel):
    token: str
    tenant_id: str = "public"


# Tighter than the chat caps — token-fishing is a real attack on this
# endpoint (someone trying random tokens), so we cap aggressively.
_VERIFY_IP_WINDOWS: tuple[Window, ...] = (
    Window(seconds=60, limit=10),
    Window(seconds=3600, limit=60),
)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return ""


@router.post("/api/auth/verify-email-token")
async def verify_email_token(body: VerifyEmailTokenBody, request: Request):
    """Consume a verification token. Returns ``OK`` or ``INVALID_TOKEN``.

    The token is single-use; a second call with the same token returns
    INVALID_TOKEN even if the email is now verified — that's expected.
    Once OK is returned, the user can sign in on any device.
    """
    token = (body.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token required")

    # Rate-limit per client IP to slow down anyone brute-forcing tokens.
    ip = _client_ip(request)
    if ip:
        breached = await _check_windows("verify-email:ip", ip, _VERIFY_IP_WINDOWS)
        if breached is not None:
            raise HTTPException(
                status_code=429,
                detail="Too many verification attempts. Try again later.",
                headers={"Retry-After": str(breached.seconds)},
            )

    try:
        result = await verify_email_using_token(body.tenant_id or "public", token)
    except Exception as exc:
        logger.warning("verify_email_using_token raised: %s", exc)
        raise HTTPException(status_code=500, detail="Verification failed")

    if isinstance(result, VerifyEmailUsingTokenOkResult):
        return {
            "status": "OK",
            "user_id": result.user.recipe_user_id.get_as_string(),
        }
    return {"status": "INVALID_TOKEN"}
