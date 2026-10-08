"""One or two jobs may call GetLeads at once, and they must not share a page.

A same-day cursor is reserved before the request, so two pe_partners jobs do
not both start at offset 0. Person keys claimed by an in-flight job are
skipped by the other until that job finishes.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Four jobs at once produced CloudFront 504s. Two at a time stays under that.
GETLEADS_CONCURRENCY = 2

_slots = threading.BoundedSemaphore(GETLEADS_CONCURRENCY)
_lock = threading.Lock()
_inflight: set[str] = set()


def getleads_slot() -> threading.BoundedSemaphore:
    return _slots


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
