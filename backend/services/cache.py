"""JSON read-through cache backed by Redis.

Used for read-heavy endpoints whose responses are stable for tens of
seconds (sidebar conversation list, in-thread messages, /api/parameters).
The pattern is *cache-aside*:

    cached = await cache_get(key)
    if cached is None:
        result = expensive_query()
        await cache_set(key, result, ttl=...)
        return result
    return cached

Writes that invalidate a cached view should call :func:`cache_invalidate`
with the same key (or :func:`cache_invalidate_prefix` to drop a whole
namespace, e.g. every message-list page for a single conversation).

If Redis is unreachable, every helper degrades gracefully: ``cache_get``
returns ``None`` (forces a re-fetch), ``cache_set`` and the invalidators
silently no-op. The chat path stays alive even with cold Redis.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from backend.services.redis_client import get_redis

logger = logging.getLogger(__name__)


async def cache_get(key: str) -> Optional[Any]:
    """Read a JSON value from Redis. Returns ``None`` on miss or error."""
    try:
        raw = await get_redis().get(f"cache:{key}")
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning("cache_get(%s) failed: %s", key, exc)
        return None


async def cache_set(key: str, value: Any, ttl: int) -> None:
    """Store a JSON-serializable value with an expiry of ``ttl`` seconds."""
    try:
        payload = json.dumps(value, default=str)
        await get_redis().set(f"cache:{key}", payload, ex=ttl)
    except Exception as exc:
        logger.warning("cache_set(%s) failed: %s", key, exc)


async def cache_invalidate(*keys: str) -> None:
    """Drop one or more cache keys."""
    if not keys:
        return
    try:
        await get_redis().delete(*(f"cache:{k}" for k in keys))
    except Exception as exc:
        logger.warning("cache_invalidate(%s) failed: %s", keys, exc)


async def cache_invalidate_prefix(prefix: str) -> None:
    """Drop every key whose name starts with ``cache:{prefix}``.

    Used when a single write affects multiple cache pages — e.g. a new
    message in conversation X should invalidate every paginated message
    list for that conversation, not just one.

    Uses ``SCAN`` to stay non-blocking; safe at the scale we expect (~100
    daily users, low key counts per prefix).
    """
    try:
        client = get_redis()
        match = f"cache:{prefix}*"
        cursor = 0
        keys_to_delete: list[str] = []
        while True:
            cursor, batch = await client.scan(cursor=cursor, match=match, count=100)
            keys_to_delete.extend(batch)
            if cursor == 0:
                break
        if keys_to_delete:
            await client.delete(*keys_to_delete)
    except Exception as exc:
        logger.warning("cache_invalidate_prefix(%s) failed: %s", prefix, exc)


# ---------------------------------------------------------------------------
# Key builders — keep all naming in one place so invalidation paths can't
# drift from the read paths.
# ---------------------------------------------------------------------------

def conv_list_key(user_id: str, course_id: Optional[str], limit: int) -> str:
    return f"convs:{user_id}:{course_id or 'all'}:{limit}"


def conv_list_prefix(user_id: str) -> str:
    return f"convs:{user_id}:"


def messages_key(conv_id: str, first_id: Optional[str], limit: int) -> str:
    return f"msgs:{conv_id}:{first_id or 'tail'}:{limit}"


def messages_prefix(conv_id: str) -> str:
    return f"msgs:{conv_id}:"


def parameters_key(course_id: str) -> str:
    return f"params:{course_id}"


# Default TTLs — short by design. The invalidation paths below should
# keep cached views correct, but a 60s ceiling makes a missed
# invalidation self-heal quickly without forcing users to refresh.
TTL_CONV_LIST = 60
TTL_MESSAGES = 30
TTL_PARAMETERS = 300
