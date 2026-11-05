"""Fixed-window rate limiting on Redis. Fails open if Redis is unreachable (availability over strictness)."""

from __future__ import annotations

import logging

from opennotebook.config import get_settings

log = logging.getLogger(__name__)


async def too_many_attempts(key: str, limit: int, window_s: int) -> bool:
    from redis.asyncio import from_url
    from redis.exceptions import RedisError

    client = from_url(get_settings().redis_url_with_auth, socket_timeout=1, socket_connect_timeout=1)
    try:
        count = await client.incr(f"rl:{key}")
        if count == 1:
            await client.expire(f"rl:{key}", window_s)
        return count > limit
    except (RedisError, OSError):
        log.warning("rate limiter unavailable, allowing request")
        return False
    finally:
        await client.aclose()
