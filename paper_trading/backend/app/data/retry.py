"""
Async retry with exponential backoff and uniform jitter.

Usage:
    from app.data.retry import async_retry

    @async_retry(max_attempts=3, base_delay=0.5)
    async def fetch_something():
        ...

    # Or inline:
    result = await async_retry(max_attempts=3)(fetch_something)()
"""
from __future__ import annotations

import asyncio
import functools
import logging
import random
from typing import Callable, Type

log = logging.getLogger(__name__)


def async_retry(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    backoff: float = 2.0,
    jitter: float = 0.25,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Decorator factory for async functions.

    Parameters
    ----------
    max_attempts : Total attempts before re-raising (includes the first try).
    base_delay   : Seconds to wait after the first failure.
    backoff      : Multiplier applied to delay on each subsequent failure.
    jitter       : Uniform jitter fraction added to each delay
                   (actual delay ∈ [delay, delay × (1 + jitter)]).
    exceptions   : Only retry on these exception types.

    Delay schedule (base_delay=0.5, backoff=2, jitter=0.25):
        Attempt 1 → fail → wait 0.50–0.625 s
        Attempt 2 → fail → wait 1.00–1.25 s
        Attempt 3 → fail → re-raise
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            delay = base_delay
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    actual_delay = delay * (1.0 + random.uniform(0.0, jitter))
                    log.warning(
                        "%s attempt %d/%d failed (%s: %s) — retrying in %.2fs",
                        fn.__name__, attempt, max_attempts,
                        type(exc).__name__, exc, actual_delay,
                    )
                    await asyncio.sleep(actual_delay)
                    delay *= backoff
            log.error(
                "%s failed after %d attempts: %s", fn.__name__, max_attempts, last_exc
            )
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator
