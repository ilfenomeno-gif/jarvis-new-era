"""Small timing helpers for observable provider and UI stages."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager


@contextmanager
def timed(
    logger: logging.Logger,
    stage: str,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> Iterator[None]:
    started = clock()
    try:
        yield
    except Exception:
        logger.exception(
            "stage=%s status=error duration_ms=%.3f",
            stage,
            (clock() - started) * 1000,
        )
        raise
    else:
        logger.info(
            "stage=%s status=ok duration_ms=%.3f",
            stage,
            (clock() - started) * 1000,
        )
