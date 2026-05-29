"""
Retry Utility
==============
Exponential backoff for external API calls.
Wraps any async function with automatic retries on failure.

Usage:
    from shared.clients.retry import with_retry

    data = await with_retry(
        fetch_something, ticker,
        max_retries=3, base_delay=1.0, name="SEC EDGAR"
    )
"""
import asyncio
import logging
from typing import TypeVar, Callable, Any

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def with_retry(
    func: Callable,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    name: str = "API call",
    **kwargs,
) -> Any:
    """
    Call an async function with exponential backoff retries.

    Args:
        func: Async function to call
        max_retries: Max number of retries (0 = no retries)
        base_delay: Initial delay in seconds (doubles each retry)
        max_delay: Maximum delay between retries
        name: Label for log messages
    """
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)

                # Special handling for rate limits
                error_str = str(e)
                if "429" in error_str or "Too Many" in error_str:
                    delay = max(delay, 30.0)  # At least 30s for rate limits
                    logger.warning(
                        f"{name}: rate limited (attempt {attempt + 1}/{max_retries + 1}), "
                        f"waiting {delay:.0f}s"
                    )
                else:
                    logger.debug(
                        f"{name}: failed (attempt {attempt + 1}/{max_retries + 1}): {e}, "
                        f"retrying in {delay:.1f}s"
                    )

                await asyncio.sleep(delay)
            else:
                logger.warning(f"{name}: failed after {max_retries + 1} attempts: {e}")

    return None  # All retries exhausted
