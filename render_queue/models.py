from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class JobStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class WorkerStatus(Enum):
    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"


@dataclass
class RenderJob:
    shot: str
    frames: int
    priority: int
    status: JobStatus = JobStatus.QUEUED
    worker: str | None = None
    retry_count: int = 0
    error: str | None = None


@dataclass
class Worker:
    name: str
    status: WorkerStatus = WorkerStatus.IDLE
    gpu_memory_mb: int | None = None
