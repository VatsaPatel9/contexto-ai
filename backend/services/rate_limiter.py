"""Redis-backed rate limiter.

Each *window* is a fixed-period counter at key
``rl:{scope}:{key}:{window_seconds}``. ``INCR`` + ``EXPIRE`` is one
round-trip per window via a pipeline; if any window's counter exceeds
its limit the request is rejected with HTTP 429.

Persistent because the data lives in Redis (AOF on in dev compose) —
counters survive backend restarts, which is the whole point.

Falls open (allows the request) if Redis is unreachable, so a brief
Redis outage never breaks the chat path.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request
from supertokens_python.recipe.session import SessionContainer
from supertokens_python.recipe.session.framework.fastapi import verify_session

from backend.services.redis_client import get_redis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Window:
    """A single rate-limit window: ``limit`` events per ``seconds``."""
    seconds: int
    limit: int

    @property
    def label(self) -> str:
        if self.seconds % 86400 == 0:
            return f"{self.seconds // 86400}d"
        if self.seconds % 3600 == 0:
            return f"{self.seconds // 3600}h"
        if self.seconds % 60 == 0:
            return f"{self.seconds // 60}m"
        return f"{self.seconds}s"


# Sensible defaults for a learning chatbot used by 6-8 graders.
# Tuned so a normal back-and-forth conversation passes, while sustained
# spam clicks or scripted hammering hits the wall fast.
CHAT_WINDOWS: tuple[Window, ...] = (
    Window(seconds=10, limit=3),       # burst
    Window(seconds=60, limit=8),       # per minute
    Window(seconds=3600, limit=80),    # per hour
    Window(seconds=86400, limit=400),  # per day
)

FEEDBACK_WINDOWS: tuple[Window, ...] = (
    Window(seconds=60, limit=30),
)

UPLOAD_WINDOWS: tuple[Window, ...] = (
    Window(seconds=3600, limit=5),
    Window(seconds=86400, limit=20),
)

# Defense-in-depth per-IP cap on the chat path. Even authenticated users
# with valid sessions can't cross this — protects against someone with
# many accounts driving from the same egress.
CHAT_IP_WINDOWS: tuple[Window, ...] = (
    Window(seconds=60, limit=30),
)


async def _check_windows(scope: str, key: str, windows: tuple[Window, ...]) -> Optional[Window]:
    """Return the first window that's now over its limit, or ``None``.

    Each window is incremented atomically and given an EXPIRE on first
    write so abandoned counters reclaim memory automatically.
    """
    if not key:
        return None
    try:
        client = get_redis()
        async with client.pipeline(transaction=False) as pipe:
            for w in windows:
                redis_key = f"rl:{scope}:{key}:{w.seconds}"
                pipe.incr(redis_key)
                pipe.expire(redis_key, w.seconds, nx=True)
            results = await pipe.execute()
        # Pipeline returns paired (incr, expire) results.
        for i, w in enumerate(windows):
            count = results[i * 2]
            if isinstance(count, int) and count > w.limit:
                return w
    except Exception as exc:  # Fail open if Redis is down — don't block users.
        logger.warning("Rate-limit check failed (allowing request): %s", exc)
    return None


def _client_ip(request: Request) -> str:
    """Best-effort client-IP extraction.

    Honors ``X-Forwarded-For`` from the nginx proxy, falls back to the
    raw socket peer. Empty string if neither is available — caller
    treats that as "skip the IP window".
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return ""


def _retry_after_header(window: Window) -> dict[str, str]:
    """Return a ``Retry-After`` header pinned to the window length.

    A more precise value would require querying the key's TTL — the
    fixed-period approximation is fine for a defensive limiter.
    """
    return {"Retry-After": str(window.seconds)}


def rate_limit_chat():
    """FastAPI dependency: per-user multi-window + per-IP global cap on chat.

    Authenticates the request (so we have a stable user_id) and then
    enforces both ``CHAT_WINDOWS`` keyed on user and ``CHAT_IP_WINDOWS``
    keyed on the client IP. Return annotation is intentionally absent —
    FastAPI mis-treats annotated return types as response models for
    dependencies built this way.
    """
    verifier = verify_session()

    async def dep(request: Request, session: SessionContainer = Depends(verifier)):
        user_id = session.get_user_id()
        ip = _client_ip(request)

        breached = await _check_windows("chat:user", user_id, CHAT_WINDOWS)
        if breached is None and ip:
            breached = await _check_windows("chat:ip", ip, CHAT_IP_WINDOWS)
        if breached is not None:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Too many requests — limit is {breached.limit} per {breached.label}. "
                    "Take a short break and try again."
                ),
                headers=_retry_after_header(breached),
            )
        return session

    return dep


def rate_limit_user(scope: str, windows: tuple[Window, ...]):
    """Generic per-user rate-limit dependency.

    Use for non-chat endpoints (feedback, uploads) where a single set of
    windows keyed on user_id is enough.
    """
    verifier = verify_session()

    async def dep(session: SessionContainer = Depends(verifier)):
        breached = await _check_windows(scope, session.get_user_id(), windows)
        if breached is not None:
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests — limit is {breached.limit} per {breached.label}.",
                headers=_retry_after_header(breached),
            )
        return session

    return dep


async def enforce_user_limits(
    user_id: str, scope: str, windows: tuple[Window, ...]
) -> None:
    """Check ``windows`` for ``user_id`` and 429 if any is over its limit.

    Use this when you already have the user_id (e.g. inside a handler
    that depends on ``require_permission``) and don't want to chain
    another dependency.
    """
    breached = await _check_windows(scope, user_id, windows)
    if breached is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests — limit is {breached.limit} per {breached.label}.",
            headers=_retry_after_header(breached),
        )


__all__ = [
    "Window",
    "CHAT_WINDOWS",
    "CHAT_IP_WINDOWS",
    "FEEDBACK_WINDOWS",
    "UPLOAD_WINDOWS",
    "rate_limit_chat",
    "rate_limit_user",
    "enforce_user_limits",
]
