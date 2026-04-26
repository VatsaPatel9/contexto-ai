"""Shared async Redis client used for rate limiting and read-side cache.

A single ``redis.asyncio.Redis`` instance is created lazily on first
access and re-used for the lifetime of the process. Connection pooling
is handled by the underlying ``redis-py`` client.

If Redis is unreachable, helpers in :mod:`backend.services.rate_limiter`
and :mod:`backend.services.cache` fall back to safe defaults (allow the
request, miss the cache) so a transient Redis outage cannot take down
the chat path.
"""

from __future__ import annotations

import logging
from typing import Optional

import redis.asyncio as redis

from backend.config import Settings

logger = logging.getLogger(__name__)

_client: Optional[redis.Redis] = None


def get_redis(settings: Optional[Settings] = None) -> redis.Redis:
    """Return the process-wide async Redis client.

    Connection-pooled. Decoded responses (``str`` instead of ``bytes``)
    so callers can read counters and JSON blobs without manual decoding.
    """
    global _client
    if _client is None:
        s = settings or Settings()
        _client = redis.from_url(
            s.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
    return _client


async def redis_healthcheck() -> bool:
    """Return ``True`` if Redis is reachable. Used by ``/health``."""
    try:
        await get_redis().ping()
        return True
    except Exception as exc:  # pragma: no cover — depends on infra
        logger.warning("Redis healthcheck failed: %s", exc)
        return False
