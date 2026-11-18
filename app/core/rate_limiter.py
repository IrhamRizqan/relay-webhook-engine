from arq.connections import ArqRedis
from fastapi import HTTPException, status

async def enforce_rate_limit(
    redis:ArqRedis,
    endpoint_id:int,
    limit_per_minute:int = 20,
)->None:
    key = f"rate_limit:endpoint:{endpoint_id}"
    current_count = await redis.incr(key)

    if current_count == 1:
        await redis.expire(key, 60)
    if current_count > limit_per_minute:
        ttl = await redis.ttl(key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit terlampaui ({limit_per_minute} event/menit). Coba lagi dalam {max(ttl, 1)} detik!"
        )