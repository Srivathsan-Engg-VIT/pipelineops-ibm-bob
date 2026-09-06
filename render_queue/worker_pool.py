"""
GPU-aware worker pool for the render queue.

Workers are loaded from a YAML config file (e.g. config/workers.yaml) so that
the worker list is never hardcoded in Python source.

# Future: discover gpu_memory_mb dynamically via nvidia-smi subprocess
"""

from __future__ import annotations

import threading
from typing import Protocol

import yaml

from render_queue.models import RenderJob, Worker, WorkerStatus


class RoutingStrategy(Protocol):
    """Strategy interface for selecting a worker for a given job."""

    def select(self, workers: list[Worker], job: RenderJob) -> Worker | None:
        """Return an IDLE worker to handle *job*, or None if none is available."""
        ...


class GPUFirstStrategy:
    """Prefer workers with gpu_memory_mb set and above *gpu_threshold_mb*.

    Falls back to any idle worker when no GPU worker is available.
    """

    def __init__(self, gpu_threshold_mb: int = 0) -> None:
        self.gpu_threshold_mb = gpu_threshold_mb

    def select(self, workers: list[Worker], job: RenderJob) -> Worker | None:
        idle = [w for w in workers if w.status == WorkerStatus.IDLE]
        if not idle:
            return None
        # Prefer GPU workers above the threshold.
        for w in idle:
            if w.gpu_memory_mb is not None and w.gpu_memory_mb > self.gpu_threshold_mb:
                return w
        # Fall back to any idle worker.
        return idle[0]


class RoundRobinStrategy:
    """Cycle through idle workers in order, ignoring GPU metadata."""

    def __init__(self) -> None:
        self._counter = 0

    def select(self, workers: list[Worker], job: RenderJob) -> Worker | None:
        idle = [w for w in workers if w.status == WorkerStatus.IDLE]
        if not idle:
            return None
        worker = idle[self._counter % len(idle)]
        self._counter += 1
        return worker


class WorkerPool:
    """Holds a collection of Workers and routes jobs via a RoutingStrategy.

    Designed to be thread-safe: all mutations to worker state go through
    set_worker_status(), which holds a lock, paving the way for concurrent
    dispatch in a future iteration.
    """

    def __init__(self, workers: list[Worker], strategy: RoutingStrategy) -> None:
        self.workers = workers
        self.strategy = strategy
        self._lock = threading.Lock()

    def find_idle_worker(self, job: RenderJob) -> Worker | None:
        """Delegate worker selection to the routing strategy."""
        with self._lock:
            return self.strategy.select(self.workers, job)

    def set_worker_status(self, name: str, status: WorkerStatus) -> None:
        """Update the status of the worker identified by *name*."""
        with self._lock:
            for w in self.workers:
                if w.name == name:
                    w.status = status
                    return

    @classmethod
    def from_config(
        cls, path: str, strategy: RoutingStrategy | None = None
    ) -> WorkerPool:
        """Load workers from a YAML file and construct a WorkerPool.

        The YAML file must have a top-level ``workers`` list where each entry
        has at minimum a ``name`` field and an optional ``gpu_memory_mb`` field.

        Args:
            path: Path to the YAML config file (e.g. ``"config/workers.yaml"``).
            strategy: Routing strategy to use; defaults to :class:`GPUFirstStrategy`.
        """
        with open(path) as fh:
            data = yaml.safe_load(fh)
        workers = [
            Worker(
                name=entry["name"],
                gpu_memory_mb=entry.get("gpu_memory_mb"),
            )
            for entry in data["workers"]
        ]
        return cls(workers=workers, strategy=strategy or GPUFirstStrategy())
