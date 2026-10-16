"""Ordered worker pools. Env knobs, sequential when workers=1."""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

from mobydick.config import env_int

T = TypeVar("T")
R = TypeVar("R")

DEFAULT_WORKERS = 8
MAX_WORKERS = 16


def worker_count(env_name: str, n_items: int = 0) -> int:
    configured = env_int(env_name, DEFAULT_WORKERS, minimum=1, maximum=MAX_WORKERS)
    if n_items <= 0:
        return configured
    return min(configured, n_items)


def map_ordered(
    fn: Callable[[T], R],
    items: list[T],
    *,
    workers: int,
    progress: Callable[[int, int], None] | None = None,
) -> list[R]:
    """Run fn over items. Sequential when workers=1. Results stay in input order."""
    if not items:
        return []
    total = len(items)
    if workers <= 1 or total <= 1:
        out: list[R] = []
        for index, item in enumerate(items, start=1):
            out.append(fn(item))
            if progress:
                progress(index, total)
        return out

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for item in items:
            ctx = contextvars.copy_context()
            futures.append(pool.submit(ctx.run, fn, item))
        out = []
        for index, future in enumerate(futures, start=1):
            out.append(future.result())
            if progress:
                progress(index, total)
    return out
