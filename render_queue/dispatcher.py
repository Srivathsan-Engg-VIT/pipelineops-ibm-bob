from __future__ import annotations

import random
import time

from render_queue.alerting import AlertNotifier, LogAlertNotifier
from render_queue.config import BACKOFF_BASE_SECONDS, MAX_RETRIES
from render_queue.logging_config import get_logger
from render_queue.models import JobStatus, RenderJob, WorkerStatus
from render_queue.worker_pool import WorkerPool

logger = get_logger(__name__)

QUEUE: list[RenderJob] = []
POOL = WorkerPool.from_config("config/workers.yaml")


def add_job(shot_name: str, frames: int, priority: int) -> RenderJob:
    job = RenderJob(shot=shot_name, frames=frames, priority=priority)
    QUEUE.append(job)
    logger.info("job_added", shot=shot_name, frames=frames, priority=priority)
    return job


def get_next_job() -> RenderJob | None:
    best: RenderJob | None = None
    for j in QUEUE:
        if j.status == JobStatus.QUEUED:
            if best is None or j.priority > best.priority:
                best = j
    return best


def dispatch(notifier: AlertNotifier = LogAlertNotifier()) -> None:
    job = get_next_job()
    if job is None:
        return
    worker = POOL.find_idle_worker(job)
    if worker is None:
        logger.warning("no_idle_workers")
        return
    job.status = JobStatus.RUNNING
    job.worker = worker.name
    POOL.set_worker_status(worker.name, WorkerStatus.BUSY)
    logger.info("job_dispatched", shot=job.shot, worker=worker.name)
    time.sleep(0.1)
    success = random.random() > 0.1
    if success:
        job.status = JobStatus.DONE
    else:
        job.retry_count += 1
        if job.retry_count < MAX_RETRIES:
            job.status = JobStatus.QUEUED
            backoff = BACKOFF_BASE_SECONDS * (2 ** (job.retry_count - 1))
            time.sleep(backoff)
        else:
            job.status = JobStatus.FAILED
            job.error = "job failed after max retries"
            notifier.notify(job)
    POOL.set_worker_status(worker.name, WorkerStatus.IDLE)
    logger.info("dispatch_result", shot=job.shot, status=job.status.value, worker=worker.name, retry_count=job.retry_count)


def run_loop(n: int) -> None:
    for _ in range(n):
        dispatch()
