"""
Job tracker with disk persistence.
Jobs survive server restarts and are stored as JSON under data/jobs/{id}/job.json.
"""
import json
import time
import uuid
from enum import Enum
from pathlib import Path

from backend.config import JOBS_DIR


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class Job:
    def __init__(self, job_id: str, description: str):
        self.id = job_id
        self.description = description
        self.status = JobStatus.PENDING
        self.progress: str = "Waiting..."
        self.result: dict | None = None
        self.error: str | None = None
        self.created_at: float = time.time()
        self.metadata: dict = {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    def save(self):
        """Persist job state to disk."""
        job_dir = JOBS_DIR / self.id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "job.json").write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def update(self, progress: str, status: "JobStatus | None" = None):
        self.progress = progress
        if status:
            self.status = status
        self.save()

    async def finish(self, result: dict):
        self.status = JobStatus.DONE
        self.result = result
        self.progress = "Done"
        self.save()

    async def fail(self, error: str):
        self.status = JobStatus.ERROR
        self.error = error
        self.progress = "Error"
        self.save()


_jobs: dict[str, Job] = {}


def _load_jobs_from_disk() -> None:
    """Load all persisted jobs from disk on startup."""
    if not JOBS_DIR.exists():
        return
    for job_dir in sorted(JOBS_DIR.iterdir(), key=lambda d: d.stat().st_mtime):
        if not job_dir.is_dir():
            continue
        job_json = job_dir / "job.json"
        if not job_json.exists():
            continue
        try:
            data = json.loads(job_json.read_text(encoding="utf-8"))
            job = Job.__new__(Job)
            job.id = data["id"]
            job.description = data["description"]
            job.status = JobStatus(data["status"])
            job.progress = data.get("progress", "")
            job.result = data.get("result")
            job.error = data.get("error")
            job.created_at = data.get("created_at", 0.0)
            job.metadata = data.get("metadata", {})
            # Jobs that were in-progress can't be resumed
            if job.status in (JobStatus.RUNNING, JobStatus.PENDING):
                job.status = JobStatus.ERROR
                job.error = (job.error or "") + "\nServer restarted while job was in progress."
                job.progress = "Error: server restarted"
                job.save()
            _jobs[job.id] = job
        except Exception:
            pass  # Skip corrupt files


_load_jobs_from_disk()


def create_job(description: str) -> Job:
    job_id = str(uuid.uuid4())
    job = Job(job_id, description)
    _jobs[job_id] = job
    job.save()
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def delete_job(job_id: str) -> bool:
    if job_id not in _jobs:
        return False
    del _jobs[job_id]
    return True


def list_jobs() -> list[dict]:
    return [j.to_dict() for j in _jobs.values()]
