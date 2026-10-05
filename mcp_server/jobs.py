"""Background job runner so HTTP clients can poll long list builds."""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from mobydick.config import settings

logger = logging.getLogger("mobydick.jobs")

JOBS_DIR = settings.jobs_dir


@dataclass
class Job:
    id: str
    kind: str
    status: str
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_public(self) -> dict[str, Any]:
        public = asdict(self)
        result = public.get("result") or {}
        if isinstance(result, dict) and "rows" in result:
            result = dict(result)
            result.pop("rows", None)
            public["result"] = result
        return public


_lock = threading.Lock()
_jobs: dict[str, Job] = {}


def _path(job_id: str) -> Path:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    return JOBS_DIR / f"{job_id}.json"


def _persist(job: Job) -> None:
    _path(job.id).write_text(json.dumps(job.to_public(), indent=2, default=str), encoding="utf-8")


def get_job(job_id: str) -> Job:
    with _lock:
        if job_id in _jobs:
            return _jobs[job_id]
    path = _path(job_id)
    if not path.exists():
        raise ValueError(f"Unknown job_id {job_id!r}")
    data = json.loads(path.read_text(encoding="utf-8"))
    job = Job(**data)
    with _lock:
        _jobs[job_id] = job
    return job


def list_jobs(limit: int = 20) -> list[Job]:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(JOBS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[Job] = []
    for path in files[:limit]:
        try:
            out.append(get_job(path.stem))
        except Exception:
            continue
    return out


def update_job_progress(job_id: str, snapshot: dict[str, Any]) -> None:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        try:
            job = get_job(job_id)
        except ValueError:
            return
    job.result = dict(snapshot)
    _persist(job)


def format_job_error(exc: BaseException) -> str:
    """Include the upstream MCP body. str(exc) alone used to drop it."""
    message = f"{type(exc).__name__}: {exc}"
    body = str(getattr(exc, "body", "") or "")
    if body and body not in message:
        message = f"{message}\n{body}"
    return message[:4000]


def start_job(
    kind: str,
    fn: Callable[[Job], dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> Job:
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind=kind,
        status="queued",
        created_at=time.time(),
        meta=meta or {},
    )
    with _lock:
        _jobs[job.id] = job
    _persist(job)

    def worker() -> None:
        job.status = "running"
        job.started_at = time.time()
        _persist(job)
        try:
            job.result = fn(job) or {}
            job.status = "completed"
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = format_job_error(exc)
            job.result = {"traceback": traceback.format_exc()[-4000:]}
            logger.error("job %s failed: %s", job.id, job.error, exc_info=True)
        finally:
            job.finished_at = time.time()
            _persist(job)

    threading.Thread(target=worker, name=f"moby-job-{job.id}", daemon=True).start()
    return job
