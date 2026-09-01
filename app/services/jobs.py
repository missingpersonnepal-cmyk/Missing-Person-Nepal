from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from ..database import SessionLocal
from ..models import BackgroundJob, utcnow

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="missing-person-job")
_lock = Lock()

@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    result: dict = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

_jobs: dict[str, Job] = {}


def _sync(job: Job, *, increment_attempt: bool = False) -> None:
    """Keep web-process work observable after restart or deploy."""
    with SessionLocal() as db:
        row = db.get(BackgroundJob, job.id)
        if row is None:
            row = BackgroundJob(id=job.id, kind=job.kind)
            db.add(row)
        row.status = job.status
        row.result = json.dumps(job.result or {}, ensure_ascii=True, default=str)
        row.error = job.error
        if job.status == "running":
            row.started_at = utcnow()
        if job.status in {"complete", "failed"}:
            row.completed_at = utcnow()
        if increment_attempt:
            row.attempts += 1
        db.commit()

def submit(kind: str, fn, *args, **kwargs) -> Job:
    job = Job(id=uuid4().hex, kind=kind)
    with _lock:
        _jobs[job.id] = job
    _sync(job)
    def run():
        job.status = "running"
        _sync(job, increment_attempt=True)
        try:
            job.result = fn(*args, **kwargs) or {}
            job.status = "complete"
        except Exception as exc:
            job.error = str(exc)[:500]
            job.status = "failed"
        _sync(job)
    _executor.submit(run)
    return job

def get(job_id: str) -> Job | None:
    with _lock:
        job = _jobs.get(job_id)
    if job is not None:
        return job
    with SessionLocal() as db:
        row = db.get(BackgroundJob, job_id)
        if row is None:
            return None
        try:
            result = json.loads(row.result or "{}")
        except json.JSONDecodeError:
            result = {}
        return Job(
            id=row.id,
            kind=row.kind,
            status=row.status,
            result=result,
            error=row.error,
            created_at=row.created_at.isoformat(),
        )
