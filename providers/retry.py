"""Bounded retries for provider calls that have not produced user-visible output."""
from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
_MAX_RETRIES = 3
_MAX_TIMEOUT = 600.0


def validate_retries(value: int | str) -> int:
    if isinstance(value, bool):
        raise ValueError("provider retries must be an integer from 0 to 3")
    try:
        retries = int(value)
    except (TypeError, ValueError):
        raise ValueError("provider retries must be an integer from 0 to 3") from None
    if str(value).strip() not in {str(retries), f"+{retries}"} or not 0 <= retries <= _MAX_RETRIES:
        raise ValueError("provider retries must be an integer from 0 to 3")
    return retries


def validate_timeout(value: int | float | str) -> float:
    if isinstance(value, bool):
        raise ValueError("provider timeout must be greater than 0 and at most 600 seconds")
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            "provider timeout must be greater than 0 and at most 600 seconds"
        ) from None
    if not math.isfinite(timeout) or not 0 < timeout <= _MAX_TIMEOUT:
        raise ValueError("provider timeout must be greater than 0 and at most 600 seconds")
    return timeout


def is_transient_provider_error(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    try:
        import httpx
    except ImportError:
        return False
    return isinstance(error, httpx.TransportError)


def _can_retry(error: Exception, attempt: int, retries: int) -> bool:
    return attempt < retries and is_transient_provider_error(error)


async def retry_call(
    operation: Callable[[], Awaitable[T]],
    retries: int,
    *,
    timeout: float = 60.0,
    delay: float = 0.1,
) -> T:
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(operation(), timeout=timeout)
        except Exception as error:
            if not _can_retry(error, attempt, retries):
                raise
            await asyncio.sleep(min(delay * (2**attempt), 1.0))
    raise RuntimeError("unreachable retry state")


async def retry_stream(
    operation: Callable[[], AsyncIterator[T]],
    retries: int,
    *,
    timeout: float = 60.0,
    delay: float = 0.1,
) -> AsyncIterator[T]:
    for attempt in range(retries + 1):
        produced_output = False
        iterator = operation().__aiter__()
        try:
            while True:
                try:
                    item = await asyncio.wait_for(iterator.__anext__(), timeout=timeout)
                except StopAsyncIteration:
                    return
                produced_output = True
                yield item
        except Exception as error:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()
            if produced_output or not _can_retry(error, attempt, retries):
                raise
            await asyncio.sleep(min(delay * (2**attempt), 1.0))
