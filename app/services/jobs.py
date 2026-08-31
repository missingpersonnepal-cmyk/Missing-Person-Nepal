from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

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

def submit(kind: str, fn, *args, **kwargs) -> Job:
    job = Job(id=uuid4().hex, kind=kind)
    with _lock:
        _jobs[job.id] = job
    def run():
        job.status = "running"
        try:
            job.result = fn(*args, **kwargs) or {}
            job.status = "complete"
        except Exception as exc:
            job.error = str(exc)[:500]
            job.status = "failed"
    _executor.submit(run)
    return job

def get(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)
