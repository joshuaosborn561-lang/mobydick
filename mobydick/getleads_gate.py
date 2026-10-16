"""One or two jobs may call GetLeads at once, and they must not share a page.

A same-day cursor is reserved before the request, so two pe_partners jobs do
not both start at offset 0. Person keys claimed by an in-flight job are
skipped by the other until that job finishes.

GETLEADS_CONCURRENCY (default 2) caps in-flight calls. Starts are also spaced
at GETLEADS_RPS (4/sec). HTTP 429 and "Too many requests" are rate limits.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from mobydick.config import env_int

# Four jobs at once produced CloudFront 504s. Two at a time stays under that.
DEFAULT_GETLEADS_CONCURRENCY = 2
GETLEADS_RPS = 4


def getleads_concurrency() -> int:
    return env_int("GETLEADS_CONCURRENCY", DEFAULT_GETLEADS_CONCURRENCY, minimum=1)


class RateLimiter:
    """Space starts so we do not exceed rps. Tests can swap clock/sleep."""

    def __init__(self, rps: float = GETLEADS_RPS) -> None:
        self.rps = rps
        self._lock = threading.Lock()
        self._next = 0.0
        self.clock = time.monotonic
        self.sleep = time.sleep

    @property
    def interval(self) -> float:
        return 1.0 / max(float(self.rps), 0.001)

    def wait(self) -> None:
        with self._lock:
            now = self.clock()
            start_at = max(now, self._next)
            self._next = start_at + self.interval
            delay = start_at - now
        if delay > 0:
            self.sleep(delay)

    def reset(self) -> None:
        with self._lock:
            self._next = 0.0


_slots_lock = threading.Lock()
_slots: threading.BoundedSemaphore | None = None
_slots_n: int | None = None
_rate_limiter = RateLimiter()
_lock = threading.Lock()
_inflight: set[str] = set()


def _semaphore() -> threading.BoundedSemaphore:
    global _slots, _slots_n
    n = getleads_concurrency()
    with _slots_lock:
        if _slots is None or _slots_n != n:
            _slots = threading.BoundedSemaphore(n)
            _slots_n = n
        return _slots


def reset_getleads_gate() -> None:
    """Rebuild the slot and rate limiter. Tests only."""
    global _slots, _slots_n
    with _slots_lock:
        _slots = None
        _slots_n = None
    _rate_limiter.reset()
    _rate_limiter.rps = GETLEADS_RPS


@contextmanager
def getleads_slot() -> Iterator[None]:
    with _semaphore():
        _rate_limiter.wait()
        yield


def filter_cursor_key(filters: dict[str, Any]) -> str:
    payload = {key: filters[key] for key in sorted(filters) if key not in {"offset", "limit", "columns"}}
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cursor_path(data_dir: Path, key: str) -> Path:
    return data_dir / "cursors" / f"{key}.json"


def reserve_search_offset(filters: dict[str, Any], limit: int, data_dir: Path) -> int:
    """Reserve the next page for this filter. A new UTC day starts again at 0."""
    width = max(1, int(limit))
    key = filter_cursor_key(filters)
    today = datetime.now(timezone.utc).date().isoformat()
    with _lock:
        path = _cursor_path(data_dir, key)
        current = 0
        if path.exists():
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                stored = {}
            if stored.get("day") == today:
                current = int(stored.get("offset") or 0)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"day": today, "offset": current + width}), encoding="utf-8")
        return current


def claim_person(key: str) -> bool:
    """True when this job is the first in-flight claim for the person."""
    if not key:
        return True
    with _lock:
        if key in _inflight:
            return False
        _inflight.add(key)
        return True


def release_people(keys: set[str]) -> None:
    with _lock:
        for key in keys:
            _inflight.discard(key)
