"""
Redis Client
============
Shared async Redis client — message bus between all services.
Workers publish raw_signals → entity resolver → resolved_signals → API.
"""
import os
import json
from typing import Optional, Any, Dict
import redis.asyncio as aioredis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

STREAMS = {
    "raw_signals": "alpha:stream:raw_signals",
    "resolved_signals": "alpha:stream:resolved_signals",
    "alerts": "alpha:stream:alerts",
    "dlq": "alpha:stream:dlq",
}

_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _client


async def publish_signal(signal_data: Dict[str, Any], stream: str = "raw_signals") -> str:
    client = await get_redis()
    entry_id: str = await client.xadd(
        STREAMS.get(stream, stream),
        {"payload": json.dumps(signal_data, default=str)},
        maxlen=100_000,
        approximate=True,
    )
    return entry_id


async def publish_to_dlq(
    original_payload: Dict[str, Any],
    error: str,
    source_stream: str = "raw_signals",
    retry_count: int = 0,
) -> str:
    """Send a failed message to the dead-letter queue with error context."""
    client = await get_redis()
    import datetime as _dt
    entry_id: str = await client.xadd(
        STREAMS["dlq"],
        {
            "payload": json.dumps(original_payload, default=str),
            "error": str(error)[:1000],
            "source_stream": source_stream,
            "retry_count": str(retry_count),
            "failed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        },
        maxlen=10_000,
        approximate=True,
    )
    return entry_id


async def cache_set(key: str, value: Any, ttl_seconds: int = 3600) -> None:
    client = await get_redis()
    await client.set(key, json.dumps(value, default=str), ex=ttl_seconds)


async def cache_get(key: str) -> Optional[Any]:
    client = await get_redis()
    value = await client.get(key)
    return json.loads(value) if value else None


async def ping() -> bool:
    try:
        return await (await get_redis()).ping()
    except Exception:
        return False
