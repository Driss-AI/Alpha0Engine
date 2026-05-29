"""
Redis Client
============
Shared async Redis client — message bus between all services.
Workers publish raw_signals → entity resolver → resolved_signals → API.

Resilience (Sprint 5):
  - connection keepalive + periodic health checks so dead sockets are noticed
  - automatic reconnect: a broken client is discarded and rebuilt on next use
  - circuit breaker: after repeated failures the client fails fast for a
    cooldown window instead of blocking every caller on connection timeouts
"""
import os
import json
import time
import logging
from typing import Optional, Any, Dict, Callable, Awaitable
import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

log = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

STREAMS = {
    "raw_signals": "alpha:stream:raw_signals",
    "resolved_signals": "alpha:stream:resolved_signals",
    "alerts": "alpha:stream:alerts",
    "dlq": "alpha:stream:dlq",
}

# Circuit breaker tuning
_CB_FAILURE_THRESHOLD = int(os.environ.get("REDIS_CB_THRESHOLD", "5"))
_CB_COOLDOWN_SECONDS = float(os.environ.get("REDIS_CB_COOLDOWN", "30"))

_client: Optional[aioredis.Redis] = None
_consecutive_failures = 0
_circuit_open_until = 0.0

_RETRYABLE = (RedisConnectionError, RedisTimeoutError, OSError)


class RedisUnavailable(RuntimeError):
    """Raised when the circuit breaker is open — Redis is presumed down."""


async def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_keepalive=True,
            socket_connect_timeout=5,
            health_check_interval=30,
            retry_on_timeout=True,
        )
    return _client


async def _reset_client() -> None:
    """Discard the cached client so the next call rebuilds the connection."""
    global _client
    old, _client = _client, None
    if old is not None:
        try:
            await old.aclose()
        except Exception:
            pass


def _circuit_open() -> bool:
    return time.monotonic() < _circuit_open_until


def _record_success() -> None:
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures = 0
    _circuit_open_until = 0.0


def _record_failure() -> None:
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures += 1
    if _consecutive_failures >= _CB_FAILURE_THRESHOLD:
        _circuit_open_until = time.monotonic() + _CB_COOLDOWN_SECONDS
        log.error(
            f"Redis circuit breaker OPEN after {_consecutive_failures} failures; "
            f"failing fast for {_CB_COOLDOWN_SECONDS:.0f}s"
        )


async def _execute(op: Callable[[aioredis.Redis], Awaitable[Any]]) -> Any:
    """Run a Redis op through the circuit breaker, reconnecting on failure."""
    if _circuit_open():
        raise RedisUnavailable("Redis circuit breaker is open")
    try:
        client = await get_redis()
        result = await op(client)
        _record_success()
        return result
    except _RETRYABLE as e:
        _record_failure()
        await _reset_client()
        log.warning(f"Redis op failed ({type(e).__name__}): {e}")
        raise


async def publish_signal(signal_data: Dict[str, Any], stream: str = "raw_signals") -> str:
    return await _execute(lambda c: c.xadd(
        STREAMS.get(stream, stream),
        {"payload": json.dumps(signal_data, default=str)},
        maxlen=100_000,
        approximate=True,
    ))


async def publish_to_dlq(
    original_payload: Dict[str, Any],
    error: str,
    source_stream: str = "raw_signals",
    retry_count: int = 0,
) -> str:
    """Send a failed message to the dead-letter queue with error context."""
    import datetime as _dt
    return await _execute(lambda c: c.xadd(
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
    ))


async def cache_set(key: str, value: Any, ttl_seconds: int = 3600) -> None:
    await _execute(lambda c: c.set(key, json.dumps(value, default=str), ex=ttl_seconds))


async def cache_get(key: str) -> Optional[Any]:
    value = await _execute(lambda c: c.get(key))
    return json.loads(value) if value else None


async def ping() -> bool:
    try:
        return bool(await _execute(lambda c: c.ping()))
    except Exception:
        return False
